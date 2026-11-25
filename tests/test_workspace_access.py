"""Authorization rules of workspace management."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.workspaces.manager import workspace_manager
from app.modules.workspaces.schemas import WorkspaceMemberInvite, WorkspaceMemberUpdate


def _user():
    return SimpleNamespace(id=uuid.uuid4())


def _ws(owner_id, type="team"):
    return SimpleNamespace(id=uuid.uuid4(), owner_id=owner_id, type=type)


def _db(scalars=()):
    db = MagicMock()
    db.scalar = AsyncMock(side_effect=list(scalars))
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.delete = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _owner_check(ws):
    return patch.object(
        workspace_manager, "_check_workspace_owner", new=AsyncMock(return_value=ws)
    )


# ── delete ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_admin_cannot_delete_the_owners_workspace():
    admin = _user()
    db = _db()
    with _owner_check(_ws(owner_id=uuid.uuid4())):
        with pytest.raises(HTTPException) as exc:
            await workspace_manager.delete_workspace(db, uuid.uuid4(), admin)
    assert exc.value.status_code == 403
    db.delete.assert_not_called()


@pytest.mark.asyncio
async def test_workspace_with_projects_is_not_deleted():
    owner = _user()
    db = _db(scalars=[2])  # two live projects
    with _owner_check(_ws(owner.id)):
        with pytest.raises(HTTPException) as exc:
            await workspace_manager.delete_workspace(db, uuid.uuid4(), owner)
    assert exc.value.detail == "workspace.not_empty"
    db.delete.assert_not_called()


@pytest.mark.asyncio
async def test_last_personal_workspace_is_kept():
    owner = _user()
    db = _db(scalars=[0, 1])  # no projects, one personal workspace
    with _owner_check(_ws(owner.id, type="personal")):
        with pytest.raises(HTTPException) as exc:
            await workspace_manager.delete_workspace(db, uuid.uuid4(), owner)
    assert exc.value.detail == "workspace.last_personal"


@pytest.mark.asyncio
async def test_owner_deletes_an_empty_team_workspace():
    owner = _user()
    ws = _ws(owner.id)
    db = _db(scalars=[0])
    with _owner_check(ws):
        await workspace_manager.delete_workspace(db, ws.id, owner)
    db.delete.assert_awaited_once_with(ws)


# ── invite / roles ───────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_personal_workspace_cannot_invite():
    owner = _user()
    with _owner_check(_ws(owner.id, type="personal")):
        with pytest.raises(HTTPException) as exc:
            await workspace_manager.invite_workspace_member(
                _db(), uuid.uuid4(), WorkspaceMemberInvite(email="a@example.com"), owner
            )
    assert exc.value.detail == "workspace.personal_cannot_invite"


def _role(**kw):
    data = {"scope": "workspace", "is_system_default": False, "workspace_id": None}
    data.update(kw)
    return SimpleNamespace(**data)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role",
    [
        None,
        _role(scope="project", is_system_default=True),
        _role(workspace_id=uuid.uuid4()),
    ],
)
async def test_foreign_or_wrong_roles_are_rejected(role):
    with pytest.raises(HTTPException) as exc:
        await workspace_manager._validate_role(
            _db(scalars=[role]), uuid.uuid4(), uuid.uuid4()
        )
    assert exc.value.detail == "workspace.invalid_role"


@pytest.mark.asyncio
async def test_own_and_system_roles_are_accepted():
    ws_id = uuid.uuid4()
    for role in (_role(workspace_id=ws_id), _role(is_system_default=True)):
        await workspace_manager._validate_role(_db(scalars=[role]), uuid.uuid4(), ws_id)
    await workspace_manager._validate_role(_db(), None, ws_id)


# ── members ──────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_admin_cannot_change_or_remove_the_owner_or_themselves():
    admin = _user()
    ws = _ws(owner_id=uuid.uuid4())
    with _owner_check(ws):
        for target in (ws.owner_id, admin.id):
            with pytest.raises(HTTPException):
                await workspace_manager.remove_workspace_member(
                    _db(), ws.id, target, admin
                )
            with pytest.raises(HTTPException):
                await workspace_manager.update_workspace_member(
                    _db(), ws.id, target, WorkspaceMemberUpdate(role_id=None), admin
                )


@pytest.mark.asyncio
async def test_removing_a_member_ends_their_project_memberships():
    owner = _user()
    ws = _ws(owner.id)
    member = SimpleNamespace(is_deleted=False, deleted_at=None)
    db = _db(scalars=[member])
    with _owner_check(ws):
        await workspace_manager.remove_workspace_member(db, ws.id, uuid.uuid4(), owner)
    assert member.is_deleted is True and member.deleted_at is not None
    sql = str(db.execute.await_args.args[0])
    assert sql.startswith("UPDATE project_members")


@pytest.mark.asyncio
async def test_removed_project_members_do_not_list_the_workspace():
    statements = []

    async def execute(stmt):
        statements.append(str(stmt))
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        return result

    db = MagicMock()
    db.execute = execute
    await workspace_manager.list_workspaces(db, _user())
    assert "project_members.is_deleted" in statements[0]


@pytest.mark.asyncio
async def test_removed_member_hands_their_projects_to_the_workspace_owner():
    owner = _user()
    ws = _ws(owner.id)
    member = SimpleNamespace(is_deleted=False, deleted_at=None)
    db = _db(scalars=[member])
    with _owner_check(ws):
        await workspace_manager.remove_workspace_member(db, ws.id, uuid.uuid4(), owner)
    statements = [str(c.args[0]) for c in db.execute.await_args_list]
    assert any(s.startswith("UPDATE projects SET owner_id") for s in statements)


def test_project_members_skip_removed_rows():
    import asyncio

    from app.modules.projects.manager import project_manager

    live = SimpleNamespace(is_deleted=False)
    gone = SimpleNamespace(is_deleted=True)
    project = SimpleNamespace(id=uuid.uuid4(), memberships=[live, gone])
    db = MagicMock()
    db.scalar = AsyncMock(return_value=1)
    asyncio.run(project_manager.attach_member_count(db, project))
    assert project.members == [live]
