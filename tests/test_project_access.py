"""Authorization tests for project endpoints: member updates, roles, deletion, workspaces."""

import importlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.projects.manager import project_manager
from app.modules.projects.schemas import (
    ProjectCreate,
    ProjectMemberCreate,
    ProjectMemberUpdate,
)

projects_router = importlib.import_module("app.modules.projects.router")
FORBIDDEN = HTTPException(
    status_code=403, detail="project.missing_permission_project.settings"
)


def _user():
    return SimpleNamespace(id=uuid.uuid4(), full_name="User")


def _project(owner_id=None, workspace_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner_id=owner_id or uuid.uuid4(),
        workspace_id=workspace_id or uuid.uuid4(),
    )


# ── update_member ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_member_cannot_give_themselves_a_role():
    me = _user()
    with (
        patch.object(
            projects_router,
            "get_project_access",
            new=AsyncMock(return_value=_project()),
        ),
        patch.object(
            project_manager, "get_member", new=AsyncMock(return_value=MagicMock())
        ),
        patch.object(
            projects_router,
            "get_project_pm_access",
            new=AsyncMock(side_effect=FORBIDDEN),
        ),
        patch.object(project_manager, "update_member", new=AsyncMock()) as update,
    ):
        with pytest.raises(HTTPException) as exc:
            await projects_router.update_member(
                uuid.uuid4(),
                me.id,
                ProjectMemberUpdate(role_id=uuid.uuid4()),
                MagicMock(),
                me,
            )
    assert exc.value.status_code == 403
    update.assert_not_awaited()


@pytest.mark.asyncio
async def test_member_can_set_their_own_telegram_thread():
    me = _user()
    with (
        patch.object(
            projects_router,
            "get_project_access",
            new=AsyncMock(return_value=_project()),
        ),
        patch.object(
            project_manager, "get_member", new=AsyncMock(return_value=MagicMock())
        ),
        patch.object(
            projects_router,
            "get_project_pm_access",
            new=AsyncMock(side_effect=FORBIDDEN),
        ) as pm,
        patch.object(
            project_manager, "update_member", new=AsyncMock(return_value="ok")
        ),
    ):
        result = await projects_router.update_member(
            uuid.uuid4(),
            me.id,
            ProjectMemberUpdate(telegram_thread_id="15"),
            MagicMock(),
            me,
        )
    assert result == "ok"
    pm.assert_not_awaited()


@pytest.mark.asyncio
async def test_member_cannot_change_someone_elses_telegram_thread():
    me = _user()
    with (
        patch.object(
            projects_router,
            "get_project_access",
            new=AsyncMock(return_value=_project()),
        ),
        patch.object(
            project_manager, "get_member", new=AsyncMock(return_value=MagicMock())
        ),
        patch.object(
            projects_router,
            "get_project_pm_access",
            new=AsyncMock(side_effect=FORBIDDEN),
        ),
    ):
        with pytest.raises(HTTPException):
            await projects_router.update_member(
                uuid.uuid4(),
                uuid.uuid4(),
                ProjectMemberUpdate(telegram_thread_id="15"),
                MagicMock(),
                me,
            )


# ── validate_role ────────────────────────────────────────────────────────────
def _role(**kw):
    data = {"scope": "project", "is_system_default": False, "workspace_id": None}
    data.update(kw)
    return SimpleNamespace(**data)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role",
    [
        None,  # missing or soft-deleted
        _role(scope="workspace", is_system_default=True),  # wrong scope
        _role(workspace_id=uuid.uuid4()),  # custom role of another workspace
    ],
)
async def test_invalid_roles_are_rejected(role):
    db = MagicMock()
    db.scalar = AsyncMock(return_value=role)
    with pytest.raises(HTTPException) as exc:
        await project_manager.validate_role(db, uuid.uuid4(), uuid.uuid4())
    assert exc.value.detail == "project.invalid_role"


@pytest.mark.asyncio
async def test_valid_roles_are_accepted():
    ws = uuid.uuid4()
    for role in (_role(is_system_default=True), _role(workspace_id=ws)):
        db = MagicMock()
        db.scalar = AsyncMock(return_value=role)
        await project_manager.validate_role(db, uuid.uuid4(), ws)
    await project_manager.validate_role(MagicMock(), None, ws)  # no role given


# ── delete_project ───────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_workspace_member_cannot_delete_project():
    me = _user()
    with (
        patch.object(
            projects_router,
            "get_project_access",
            new=AsyncMock(return_value=_project()),
        ),
        patch.object(
            projects_router.rbac_manager,
            "_check_workspace_admin_access",
            new=AsyncMock(return_value=False),
        ),
        patch.object(project_manager, "soft_delete", new=AsyncMock()) as delete,
    ):
        with pytest.raises(HTTPException) as exc:
            await projects_router.delete_project(uuid.uuid4(), MagicMock(), me)
    assert exc.value.status_code == 403
    delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_and_workspace_admin_can_delete_project():
    me = _user()
    for project, admin in ((_project(owner_id=me.id), False), (_project(), True)):
        with (
            patch.object(
                projects_router,
                "get_project_access",
                new=AsyncMock(return_value=project),
            ),
            patch.object(
                projects_router.rbac_manager,
                "_check_workspace_admin_access",
                new=AsyncMock(return_value=admin),
            ),
            patch.object(project_manager, "soft_delete", new=AsyncMock()) as delete,
        ):
            await projects_router.delete_project(project.id, MagicMock(), me)
        delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_soft_delete_keeps_the_project_row():
    project = SimpleNamespace(is_deleted=False, deleted_at=None, deleted_by=None)
    db = MagicMock()
    db.flush = AsyncMock()
    user_id = uuid.uuid4()
    await project_manager.soft_delete(db, project, user_id)
    assert (
        project.is_deleted is True
        and project.deleted_by == user_id
        and project.deleted_at is not None
    )
    db.delete.assert_not_called()


# ── workspaces ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_cannot_create_project_in_a_foreign_workspace():
    with (
        patch.object(
            project_manager, "is_workspace_member", new=AsyncMock(return_value=False)
        ),
        patch.object(
            project_manager, "create_project_with_owner", new=AsyncMock()
        ) as create,
    ):
        with pytest.raises(HTTPException) as exc:
            await projects_router.create_project(
                ProjectCreate(name="p", workspace_id=uuid.uuid4()), MagicMock(), _user()
            )
    assert exc.value.status_code == 403
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_cannot_create_project_without_a_workspace():
    with patch.object(
        project_manager, "create_project_with_owner", new=AsyncMock()
    ) as create:
        with pytest.raises(HTTPException) as exc:
            await projects_router.create_project(
                ProjectCreate(name="p"), MagicMock(), _user()
            )
    assert exc.value.status_code == 422
    assert exc.value.detail == "project.workspace_required"
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_workspace_owner_counts_as_member():
    owner = uuid.uuid4()
    db = MagicMock()
    db.scalar = AsyncMock(return_value=owner)
    assert await project_manager.is_workspace_member(db, uuid.uuid4(), owner) is True


@pytest.mark.asyncio
async def test_team_project_only_accepts_workspace_members():
    project = _project()
    db = MagicMock()
    db.get = AsyncMock(return_value=SimpleNamespace(type="team"))
    with (
        patch.object(
            projects_router,
            "get_project_pm_access",
            new=AsyncMock(return_value=project),
        ),
        patch.object(project_manager, "get_member", new=AsyncMock(return_value=None)),
        patch.object(
            projects_router.user_manager,
            "get",
            new=AsyncMock(return_value=SimpleNamespace(full_name="X")),
        ),
        patch.object(project_manager, "validate_role", new=AsyncMock()),
        patch.object(
            project_manager, "is_workspace_member", new=AsyncMock(return_value=False)
        ),
        patch.object(project_manager, "add_member", new=AsyncMock()) as add,
    ):
        with pytest.raises(HTTPException) as exc:
            await projects_router.add_member(
                project.id,
                ProjectMemberCreate(user_id=uuid.uuid4()),
                MagicMock(),
                db,
                _user(),
            )
    assert exc.value.detail == "project.user_not_in_workspace"
    add.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("member_row, expected", [(uuid.uuid4(), True), (None, False)])
async def test_workspace_membership_query(member_row, expected):
    """Runs the real queries (compiled to SQL) for a user who is not the owner."""
    statements = []

    async def scalar(stmt):
        statements.append(str(stmt))
        return uuid.uuid4() if len(statements) == 1 else member_row  # owner differs

    db = MagicMock()
    db.scalar = scalar
    assert (
        await project_manager.is_workspace_member(db, uuid.uuid4(), uuid.uuid4())
        is expected
    )
    assert "workspace_members.user_id" in statements[1]
    assert "is_deleted" in statements[1]


def test_workspace_owner_gets_project_access():
    """get_project_for_user's query also matches the workspace owner."""
    from sqlalchemy.dialects import postgresql

    captured = {}

    async def execute(stmt):
        captured["sql"] = str(stmt.compile(dialect=postgresql.dialect()))
        result = MagicMock()
        result.scalars.return_value.first.return_value = None
        return result

    import asyncio

    db = MagicMock()
    db.execute = execute
    asyncio.run(project_manager.get_project_for_user(db, uuid.uuid4(), uuid.uuid4()))
    assert "workspaces.owner_id" in captured["sql"]
