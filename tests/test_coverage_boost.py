"""Tests targeting uncovered lines to push coverage above 70%."""

import uuid
from datetime import date, timedelta, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.exc import IntegrityError, OperationalError

import pytest


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_user(**kw):
    u = MagicMock()
    u.id = kw.get("id", uuid.uuid4())
    u.email = kw.get("email", "u@test.com")
    u.system_role = kw.get("system_role", "user")
    return u


def _make_ws(owner_id=None):
    ws = MagicMock()
    ws.id = uuid.uuid4()
    ws.owner_id = owner_id or uuid.uuid4()
    ws.is_deleted = False
    return ws


def _scalars_result(items=None, first=None):
    sc = MagicMock()
    sc.all.return_value = items if items is not None else []
    sc.first.return_value = first
    r = MagicMock()
    r.scalars.return_value = sc
    r.scalar_one_or_none.return_value = first
    return r


# ─── WorkspaceManager: _check_workspace_owner with RBAC admin ────────────────


@pytest.mark.asyncio
async def test_check_workspace_owner_non_owner_admin():
    from app.modules.workspaces.manager import workspace_manager

    user = _make_user()
    ws = _make_ws(owner_id=uuid.uuid4())  # different owner

    db = AsyncMock()
    db.get = AsyncMock(return_value=ws)

    with patch("app.modules.workspaces.manager.rbac_manager") as mock_rbac:
        mock_rbac.check_permission = AsyncMock(return_value=True)
        result = await workspace_manager._check_workspace_owner(db, ws.id, user.id)
    assert result == ws


@pytest.mark.asyncio
async def test_check_workspace_owner_non_owner_denied():
    from fastapi import HTTPException
    from app.modules.workspaces.manager import workspace_manager

    user = _make_user()
    ws = _make_ws(owner_id=uuid.uuid4())

    db = AsyncMock()
    db.get = AsyncMock(return_value=ws)

    with patch("app.modules.workspaces.manager.rbac_manager") as mock_rbac:
        mock_rbac.check_permission = AsyncMock(return_value=False)
        with pytest.raises(HTTPException) as exc:
            await workspace_manager._check_workspace_owner(db, ws.id, user.id)
    assert exc.value.status_code == 403


# ─── WorkspaceManager: create_workspace unhandled exception ──────────────────


@pytest.mark.asyncio
async def test_create_workspace_unhandled_exception():
    from app.modules.workspaces.manager import workspace_manager
    from app.modules.workspaces.schemas import WorkspaceCreate

    db = AsyncMock()
    user = _make_user()
    db.add = MagicMock()
    db.commit = AsyncMock(side_effect=RuntimeError("unexpected"))
    db.rollback = AsyncMock()

    ws_in = WorkspaceCreate(name="WS", type="personal")
    with pytest.raises(RuntimeError):
        await workspace_manager.create_workspace(db, ws_in, user)


# ─── WorkspaceManager: update_workspace with settings + exceptions ────────────


@pytest.mark.asyncio
async def test_update_workspace_with_settings():
    from app.modules.workspaces.manager import workspace_manager
    from app.modules.workspaces.schemas import WorkspaceUpdate, WorkspaceSettings

    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db = AsyncMock()
    db.get = AsyncMock(return_value=ws)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    settings = WorkspaceSettings()
    ws_in = WorkspaceUpdate(settings=settings)
    await workspace_manager.update_workspace(db, ws.id, ws_in, user)
    assert ws.settings is not None


@pytest.mark.asyncio
async def test_update_workspace_unhandled_exception():
    from app.modules.workspaces.manager import workspace_manager
    from app.modules.workspaces.schemas import WorkspaceUpdate

    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db = AsyncMock()
    db.get = AsyncMock(return_value=ws)
    db.commit = AsyncMock(side_effect=RuntimeError("boom"))
    db.rollback = AsyncMock()

    with pytest.raises(RuntimeError):
        await workspace_manager.update_workspace(
            db, ws.id, WorkspaceUpdate(name="NewName"), user
        )


# ─── WorkspaceManager: delete_workspace unhandled exception ──────────────────


@pytest.mark.asyncio
async def test_delete_workspace_unhandled_exception():
    from app.modules.workspaces.manager import workspace_manager

    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db = AsyncMock()
    db.get = AsyncMock(return_value=ws)
    db.delete = AsyncMock()
    db.commit = AsyncMock(side_effect=RuntimeError("boom"))
    db.rollback = AsyncMock()

    with pytest.raises(RuntimeError):
        await workspace_manager.delete_workspace(db, ws.id, user)


# ─── WorkspaceManager: update_workspace_member exceptions ────────────────────


@pytest.mark.asyncio
async def test_update_workspace_member_integrity_error():
    from fastapi import HTTPException
    from app.modules.workspaces.manager import workspace_manager
    from app.modules.workspaces.schemas import WorkspaceMemberUpdate

    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db = AsyncMock()
    db.get = AsyncMock(return_value=ws)

    mem = MagicMock()
    db.scalar = AsyncMock(return_value=mem)
    db.commit = AsyncMock(side_effect=IntegrityError("dup", None, None))
    db.rollback = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await workspace_manager.update_workspace_member(
            db, ws.id, uuid.uuid4(), WorkspaceMemberUpdate(role_id=uuid.uuid4()), user
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_workspace_member_operational_error():
    from fastapi import HTTPException
    from app.modules.workspaces.manager import workspace_manager
    from app.modules.workspaces.schemas import WorkspaceMemberUpdate

    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db = AsyncMock()
    db.get = AsyncMock(return_value=ws)

    mem = MagicMock()
    db.scalar = AsyncMock(return_value=mem)
    db.commit = AsyncMock(side_effect=OperationalError("db", None, None))
    db.rollback = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await workspace_manager.update_workspace_member(
            db, ws.id, uuid.uuid4(), WorkspaceMemberUpdate(role_id=uuid.uuid4()), user
        )
    assert exc.value.status_code == 503


# ─── WorkspaceManager: remove_workspace_member exception ─────────────────────


@pytest.mark.asyncio
async def test_remove_workspace_member_integrity_error():
    from fastapi import HTTPException
    from app.modules.workspaces.manager import workspace_manager

    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db = AsyncMock()
    db.get = AsyncMock(return_value=ws)

    mem = MagicMock()
    mem.is_deleted = False
    db.scalar = AsyncMock(return_value=mem)
    db.commit = AsyncMock(side_effect=IntegrityError("ref", None, None))
    db.rollback = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await workspace_manager.remove_workspace_member(db, ws.id, uuid.uuid4(), user)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_remove_workspace_member_operational_error():
    from fastapi import HTTPException
    from app.modules.workspaces.manager import workspace_manager

    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db = AsyncMock()
    db.get = AsyncMock(return_value=ws)

    mem = MagicMock()
    mem.is_deleted = False
    db.scalar = AsyncMock(return_value=mem)
    db.commit = AsyncMock(side_effect=OperationalError("db", None, None))
    db.rollback = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await workspace_manager.remove_workspace_member(db, ws.id, uuid.uuid4(), user)
    assert exc.value.status_code == 503


# ─── WorkspaceManager: invite_workspace_member exceptions ────────────────────


@pytest.mark.asyncio
async def test_invite_workspace_member_integrity_error():
    from fastapi import HTTPException
    from app.modules.workspaces.manager import workspace_manager
    from app.modules.workspaces.schemas import WorkspaceMemberInvite

    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db = AsyncMock()
    db.get = AsyncMock(return_value=ws)
    db.scalar = AsyncMock(return_value=None)  # user not found
    db.add = MagicMock()
    db.commit = AsyncMock(side_effect=IntegrityError("dup", None, None))
    db.rollback = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await workspace_manager.invite_workspace_member(
            db, ws.id, WorkspaceMemberInvite(email="a@b.com"), user
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_invite_workspace_member_operational_error():
    from fastapi import HTTPException
    from app.modules.workspaces.manager import workspace_manager
    from app.modules.workspaces.schemas import WorkspaceMemberInvite

    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db = AsyncMock()
    db.get = AsyncMock(return_value=ws)
    db.scalar = AsyncMock(return_value=None)
    db.add = MagicMock()
    db.commit = AsyncMock(side_effect=OperationalError("db", None, None))
    db.rollback = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await workspace_manager.invite_workspace_member(
            db, ws.id, WorkspaceMemberInvite(email="a@b.com"), user
        )
    assert exc.value.status_code == 503


# ─── WorkspaceManager: cancel_workspace_invitation ───────────────────────────


@pytest.mark.asyncio
async def test_cancel_invitation_not_found():
    from fastapi import HTTPException
    from app.modules.workspaces.manager import workspace_manager

    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db = AsyncMock()
    db.get = AsyncMock(return_value=ws)
    db.scalar = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await workspace_manager.cancel_workspace_invitation(
            db, ws.id, uuid.uuid4(), user
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_cancel_invitation_success():
    from app.modules.workspaces.manager import workspace_manager

    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db = AsyncMock()
    db.get = AsyncMock(return_value=ws)

    inv = MagicMock()
    inv.is_deleted = False
    inv.status = "pending"
    db.scalar = AsyncMock(return_value=inv)
    db.commit = AsyncMock()

    await workspace_manager.cancel_workspace_invitation(db, ws.id, uuid.uuid4(), user)
    assert inv.is_deleted is True
    assert inv.status == "cancelled"


@pytest.mark.asyncio
async def test_cancel_invitation_integrity_error():
    from fastapi import HTTPException
    from app.modules.workspaces.manager import workspace_manager

    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db = AsyncMock()
    db.get = AsyncMock(return_value=ws)

    inv = MagicMock()
    db.scalar = AsyncMock(return_value=inv)
    db.commit = AsyncMock(side_effect=IntegrityError("x", None, None))
    db.rollback = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await workspace_manager.cancel_workspace_invitation(
            db, ws.id, uuid.uuid4(), user
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_cancel_invitation_operational_error():
    from fastapi import HTTPException
    from app.modules.workspaces.manager import workspace_manager

    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db = AsyncMock()
    db.get = AsyncMock(return_value=ws)

    inv = MagicMock()
    db.scalar = AsyncMock(return_value=inv)
    db.commit = AsyncMock(side_effect=OperationalError("db", None, None))
    db.rollback = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await workspace_manager.cancel_workspace_invitation(
            db, ws.id, uuid.uuid4(), user
        )
    assert exc.value.status_code == 503


# ─── RBACManager: check_permission with project_id lookup ────────────────────


@pytest.mark.asyncio
async def test_check_permission_with_project_ws_lookup():
    from app.modules.rbac.manager import rbac_manager

    db = AsyncMock()
    ws_id = uuid.uuid4()
    db.scalar = AsyncMock(return_value=ws_id)

    with patch.object(
        rbac_manager,
        "get_user_permissions",
        new=AsyncMock(return_value={"task.create"}),
    ):
        result = await rbac_manager.check_permission(
            db, uuid.uuid4(), "task.create", project_id=uuid.uuid4()
        )
    assert result is True


@pytest.mark.asyncio
async def test_check_permission_project_ws_not_found():
    from app.modules.rbac.manager import rbac_manager

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)

    result = await rbac_manager.check_permission(
        db, uuid.uuid4(), "task.create", project_id=uuid.uuid4()
    )
    assert result is False


# ─── RBACManager: _check_workspace_admin_access ──────────────────────────────


@pytest.mark.asyncio
async def test_check_workspace_admin_access_owner():
    from app.modules.rbac.manager import rbac_manager

    user_id = uuid.uuid4()
    db = AsyncMock()
    ws = MagicMock()
    ws.owner_id = user_id
    db.scalar = AsyncMock(return_value=ws)

    result = await rbac_manager._check_workspace_admin_access(db, user_id, uuid.uuid4())
    assert result is True


@pytest.mark.asyncio
async def test_check_workspace_admin_access_non_owner():
    from app.modules.rbac.manager import rbac_manager

    user_id = uuid.uuid4()
    db = AsyncMock()
    ws = MagicMock()
    ws.owner_id = uuid.uuid4()  # different
    db.scalar = AsyncMock(return_value=ws)

    with patch.object(
        rbac_manager, "check_permission", new=AsyncMock(return_value=True)
    ):
        result = await rbac_manager._check_workspace_admin_access(
            db, user_id, uuid.uuid4()
        )
    assert result is True


# ─── RBACManager: create_role with workspace access check ────────────────────


@pytest.mark.asyncio
async def test_create_role_with_workspace_access():
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleCreate

    db = AsyncMock()
    user = _make_user()
    user.id = uuid.uuid4()
    ws_id = uuid.uuid4()

    db.add = MagicMock()
    db.commit = AsyncMock()

    mock_role = MagicMock()
    db.execute.return_value = _scalars_result(first=mock_role)

    with patch.object(
        rbac_manager, "_check_workspace_admin_access", new=AsyncMock(return_value=True)
    ):
        role_in = RoleCreate(name="Custom Role", scope="workspace", workspace_id=ws_id)
        await rbac_manager.create_role(db, role_in, user)

    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_create_role_with_workspace_no_access():
    from fastapi import HTTPException
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleCreate

    db = AsyncMock()
    user = _make_user()
    ws_id = uuid.uuid4()

    with patch.object(
        rbac_manager, "_check_workspace_admin_access", new=AsyncMock(return_value=False)
    ):
        role_in = RoleCreate(name="Custom Role", scope="workspace", workspace_id=ws_id)
        with pytest.raises(HTTPException) as exc:
            await rbac_manager.create_role(db, role_in, user)
    assert exc.value.status_code == 403


# ─── RBACManager: update_role exceptions ────────────────────────────────────


@pytest.mark.asyncio
async def test_update_role_integrity_error():
    from fastapi import HTTPException
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleUpdate

    db = AsyncMock()
    mock_role = MagicMock()
    mock_role.is_system_default = False
    mock_role.workspace_id = None
    mock_role.name = "Old"
    mock_role.id = uuid.uuid4()
    db.scalar = AsyncMock(return_value=mock_role)
    db.commit = AsyncMock(side_effect=IntegrityError("dup", None, None))
    db.rollback = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await rbac_manager.update_role(
            db, uuid.uuid4(), RoleUpdate(name="New"), _make_user()
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_role_with_description():
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleUpdate

    db = AsyncMock()
    mock_role = MagicMock()
    mock_role.is_system_default = False
    mock_role.workspace_id = None
    mock_role.name = "Dev"
    mock_role.description = "old desc"
    mock_role.id = uuid.uuid4()
    db.scalar = AsyncMock(return_value=mock_role)
    db.commit = AsyncMock()
    db.execute.return_value = _scalars_result(first=mock_role)

    await rbac_manager.update_role(
        db, uuid.uuid4(), RoleUpdate(name="Dev", description="new desc"), _make_user()
    )
    assert mock_role.description == "new desc"


@pytest.mark.asyncio
async def test_update_role_with_workspace_access():
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleUpdate

    db = AsyncMock()
    ws_id = uuid.uuid4()
    mock_role = MagicMock()
    mock_role.is_system_default = False
    mock_role.workspace_id = ws_id
    mock_role.name = "Dev"
    mock_role.id = uuid.uuid4()
    db.scalar = AsyncMock(return_value=mock_role)
    db.commit = AsyncMock()
    db.execute.return_value = _scalars_result(first=mock_role)

    with patch.object(
        rbac_manager, "_check_workspace_admin_access", new=AsyncMock(return_value=True)
    ):
        await rbac_manager.update_role(
            db, uuid.uuid4(), RoleUpdate(name="New"), _make_user()
        )


@pytest.mark.asyncio
async def test_update_role_with_workspace_no_access():
    from fastapi import HTTPException
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleUpdate

    db = AsyncMock()
    ws_id = uuid.uuid4()
    mock_role = MagicMock()
    mock_role.is_system_default = False
    mock_role.workspace_id = ws_id
    db.scalar = AsyncMock(return_value=mock_role)

    with patch.object(
        rbac_manager, "_check_workspace_admin_access", new=AsyncMock(return_value=False)
    ):
        with pytest.raises(HTTPException) as exc:
            await rbac_manager.update_role(
                db, uuid.uuid4(), RoleUpdate(name="X"), _make_user()
            )
    assert exc.value.status_code == 403


# ─── RBACManager: update_role_permissions with workspace check ───────────────


@pytest.mark.asyncio
async def test_update_role_permissions_workspace_no_access():
    from fastapi import HTTPException
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleUpdatePermissions

    db = AsyncMock()
    ws_id = uuid.uuid4()
    mock_role = MagicMock()
    mock_role.is_system_default = False
    mock_role.workspace_id = ws_id
    mock_role.permissions = []
    db.scalar = AsyncMock(return_value=mock_role)

    with patch.object(
        rbac_manager, "_check_workspace_admin_access", new=AsyncMock(return_value=False)
    ):
        with pytest.raises(HTTPException) as exc:
            await rbac_manager.update_role_permissions(
                db, uuid.uuid4(), RoleUpdatePermissions(permission_ids=[]), _make_user()
            )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_update_role_permissions_invalid_perm_ids():
    from fastapi import HTTPException
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleUpdatePermissions

    db = AsyncMock()
    mock_role = MagicMock()
    mock_role.is_system_default = False
    mock_role.workspace_id = None
    mock_role.permissions = []
    db.scalar = AsyncMock(return_value=mock_role)

    # returns empty list but we pass 2 IDs → count mismatch
    mock_sc = MagicMock()
    mock_sc.all.return_value = []
    mock_res = MagicMock()
    mock_res.scalars.return_value = mock_sc
    db.execute = AsyncMock(return_value=mock_res)

    with pytest.raises(HTTPException) as exc:
        await rbac_manager.update_role_permissions(
            db,
            uuid.uuid4(),
            RoleUpdatePermissions(permission_ids=[uuid.uuid4(), uuid.uuid4()]),
            _make_user(),
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_update_role_permissions_integrity_error():
    from fastapi import HTTPException
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleUpdatePermissions

    db = AsyncMock()
    mock_role = MagicMock()
    mock_role.is_system_default = False
    mock_role.workspace_id = None
    mock_role.permissions = []
    db.scalar = AsyncMock(return_value=mock_role)

    mock_perm = MagicMock()
    mock_sc = MagicMock()
    mock_sc.all.return_value = [mock_perm]
    mock_res = MagicMock()
    mock_res.scalars.return_value = mock_sc
    db.execute = AsyncMock(return_value=mock_res)
    db.commit = AsyncMock(side_effect=IntegrityError("dup", None, None))
    db.rollback = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await rbac_manager.update_role_permissions(
            db,
            uuid.uuid4(),
            RoleUpdatePermissions(permission_ids=[uuid.uuid4()]),
            _make_user(),
        )
    assert exc.value.status_code == 409


# ─── RBACManager: delete_role with workspace check + exceptions ───────────────


@pytest.mark.asyncio
async def test_delete_role_with_workspace_access():
    from app.modules.rbac.manager import rbac_manager

    db = AsyncMock()
    ws_id = uuid.uuid4()
    mock_role = MagicMock()
    mock_role.is_system_default = False
    mock_role.workspace_id = ws_id
    mock_role.is_deleted = False
    db.scalar = AsyncMock(return_value=mock_role)
    db.commit = AsyncMock()

    with patch.object(
        rbac_manager, "_check_workspace_admin_access", new=AsyncMock(return_value=True)
    ):
        await rbac_manager.delete_role(db, uuid.uuid4(), _make_user())
    assert mock_role.is_deleted is True


@pytest.mark.asyncio
async def test_delete_role_with_workspace_no_access():
    from fastapi import HTTPException
    from app.modules.rbac.manager import rbac_manager

    db = AsyncMock()
    ws_id = uuid.uuid4()
    mock_role = MagicMock()
    mock_role.is_system_default = False
    mock_role.workspace_id = ws_id
    db.scalar = AsyncMock(return_value=mock_role)

    with patch.object(
        rbac_manager, "_check_workspace_admin_access", new=AsyncMock(return_value=False)
    ):
        with pytest.raises(HTTPException) as exc:
            await rbac_manager.delete_role(db, uuid.uuid4(), _make_user())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_delete_role_integrity_error():
    from fastapi import HTTPException
    from app.modules.rbac.manager import rbac_manager

    db = AsyncMock()
    mock_role = MagicMock()
    mock_role.is_system_default = False
    mock_role.workspace_id = None
    mock_role.is_deleted = False
    db.scalar = AsyncMock(return_value=mock_role)
    db.commit = AsyncMock(side_effect=IntegrityError("ref", None, None))
    db.rollback = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await rbac_manager.delete_role(db, uuid.uuid4(), _make_user())
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_delete_role_operational_error():
    from fastapi import HTTPException
    from app.modules.rbac.manager import rbac_manager

    db = AsyncMock()
    mock_role = MagicMock()
    mock_role.is_system_default = False
    mock_role.workspace_id = None
    mock_role.is_deleted = False
    db.scalar = AsyncMock(return_value=mock_role)
    db.commit = AsyncMock(side_effect=OperationalError("db", None, None))
    db.rollback = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await rbac_manager.delete_role(db, uuid.uuid4(), _make_user())
    assert exc.value.status_code == 503


# ─── EpicManager ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_epic_manager_get_by_workspace():
    from app.modules.epics.manager import epic_manager

    db = AsyncMock()
    epics = [MagicMock(), MagicMock()]
    db.execute.return_value = _scalars_result(items=epics)

    result = await epic_manager.get_epics_by_workspace(db, uuid.uuid4())
    assert len(result) == 2


@pytest.mark.asyncio
async def test_epic_manager_get_by_project():
    from app.modules.epics.manager import epic_manager

    db = AsyncMock()
    epics = [MagicMock()]
    db.execute.return_value = _scalars_result(items=epics)

    result = await epic_manager.get_epics_by_project(db, uuid.uuid4())
    assert len(result) == 1


# ─── TaskManager: subtask deadline validation ─────────────────────────────────


@pytest.mark.asyncio
async def test_create_task_subtask_deadline_exceeded():
    from fastapi import HTTPException
    from app.modules.tasks.manager import task_manager
    from app.modules.tasks.schemas import TaskCreate
    from datetime import datetime as dt

    db = AsyncMock()
    project_id = uuid.uuid4()
    parent_id = uuid.uuid4()

    parent_task = MagicMock()
    parent_task.parent_task_id = None  # not a sub-subtask
    parent_task.deadline = dt.now() + timedelta(days=3)

    mock_project = MagicMock()
    mock_project.workspace_id = uuid.uuid4()

    results = [parent_task, mock_project, parent_task]
    idx = [0]

    def get_side(model, id_val):
        r = results[idx[0]]
        idx[0] += 1
        return r

    db.get = AsyncMock(side_effect=get_side)
    db.add = MagicMock()

    mock_pos = MagicMock()
    mock_pos.scalar.return_value = None
    db.execute = AsyncMock(return_value=mock_pos)

    obj_in = TaskCreate(
        title="Subtask",
        project_id=project_id,
        parent_task_id=parent_id,
        deadline=date.today() + timedelta(days=10),
    )

    with pytest.raises(HTTPException) as exc:
        await task_manager.create_task(db, obj_in=obj_in, creator_id=uuid.uuid4())
    assert exc.value.status_code == 400
    assert "deadline" in exc.value.detail


# ─── TaskManager: update with cascade sprint/epic ────────────────────────────


@pytest.mark.asyncio
async def test_task_update_cascade_sprint():
    from app.modules.tasks.manager import task_manager
    from app.modules.tasks.schemas import TaskUpdate

    db = AsyncMock()
    task = MagicMock()
    task.id = uuid.uuid4()
    task.project_id = uuid.uuid4()
    task.parent_task_id = None
    task.sprint_id = uuid.uuid4()
    task.epic_id = uuid.uuid4()
    task.deadline = None

    new_sprint_id = uuid.uuid4()
    mock_sc = MagicMock()
    mock_sc.scalars.return_value.all.return_value = []
    mock_sc.scalar_one_or_none.return_value = task
    db.execute = AsyncMock(return_value=mock_sc)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    result = await task_manager.update(
        db, db_obj=task, obj_in=TaskUpdate(sprint_id=new_sprint_id)
    )
    assert result == task


# ─── TaskManager: update_status cascade ──────────────────────────────────────


@pytest.mark.asyncio
async def test_update_status_cascade_in_progress():
    from app.modules.tasks.manager import task_manager

    db = AsyncMock()
    task = MagicMock()
    task.id = uuid.uuid4()
    task.status = "todo"

    subtask = MagicMock()
    subtask.status = "todo"

    call_count = 0

    def exec_side(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_sc = MagicMock()
        if call_count == 1:
            # deps check — return empty (no unfinished deps)
            mock_sc.scalars.return_value.all.return_value = []
        else:
            # subtasks cascade query
            mock_sc.scalars.return_value.all.return_value = [subtask]
        return mock_sc

    db.execute = AsyncMock(side_effect=exec_side)

    await task_manager.update_status(db, task, "in_progress")
    assert task.status == "in_progress"
    assert subtask.status == "in_progress"


@pytest.mark.asyncio
async def test_update_status_cascade_review():
    from app.modules.tasks.manager import task_manager

    db = AsyncMock()
    task = MagicMock()
    task.id = uuid.uuid4()
    task.status = "in_progress"

    subtask = MagicMock()
    subtask.status = "in_progress"

    mock_sc = MagicMock()
    mock_sc.scalars.return_value.all.return_value = [subtask]
    db.execute = AsyncMock(return_value=mock_sc)

    await task_manager.update_status(db, task, "review")
    assert task.status == "review"
    assert subtask.status == "review"


# ─── TaskManager: update_position ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_position_same_status():
    from app.modules.tasks.manager import task_manager

    db = AsyncMock()
    task = MagicMock()
    task.id = uuid.uuid4()
    task.project_id = uuid.uuid4()
    task.status = "todo"
    task.position = 1

    other_task = MagicMock()
    other_task.id = uuid.uuid4()
    other_task.position = 2

    mock_sc = MagicMock()
    mock_sc.scalars.return_value.all.return_value = [task, other_task]
    db.execute = AsyncMock(return_value=mock_sc)

    await task_manager.update_position(db, task, "todo")
    assert task.position >= 1


@pytest.mark.asyncio
async def test_update_position_with_insert_after():
    from app.modules.tasks.manager import task_manager

    db = AsyncMock()
    after_id = uuid.uuid4()
    task = MagicMock()
    task.id = uuid.uuid4()
    task.project_id = uuid.uuid4()
    task.status = "todo"
    task.position = 3

    anchor = MagicMock()
    anchor.id = after_id
    anchor.position = 1

    other = MagicMock()
    other.id = uuid.uuid4()
    other.position = 2

    mock_sc = MagicMock()
    mock_sc.scalars.return_value.all.return_value = [anchor, other]
    db.execute = AsyncMock(return_value=mock_sc)

    result = await task_manager.update_position(
        db, task, "todo", insert_after_id=after_id
    )
    assert result == task


# ─── TaskManager: update with subtask deadline validation ────────────────────


@pytest.mark.asyncio
async def test_task_update_subtask_deadline_check():
    from fastapi import HTTPException
    from app.modules.tasks.manager import task_manager

    db = AsyncMock()
    parent_id = uuid.uuid4()
    parent_task = MagicMock()
    parent_task.deadline = date.today() + timedelta(days=2)

    task = MagicMock()
    task.id = uuid.uuid4()
    task.parent_task_id = parent_id
    task.sprint_id = None
    task.epic_id = None
    task.deadline = date.today() + timedelta(days=1)

    db.get = AsyncMock(return_value=parent_task)
    mock_sc = MagicMock()
    mock_sc.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=mock_sc)

    # New deadline exceeds parent
    with pytest.raises(HTTPException) as exc:
        await task_manager.update(
            db, db_obj=task, obj_in={"deadline": date.today() + timedelta(days=10)}
        )
    assert exc.value.status_code == 400


# ─── SprintManager: get_stats with started_at set ────────────────────────────


@pytest.mark.asyncio
async def test_sprint_get_stats_with_started_at():
    from app.modules.sprints.manager import sprint_manager

    db = AsyncMock()
    sprint = MagicMock()
    sprint.id = uuid.uuid4()
    sprint.status = "active"
    sprint.started_at = datetime.now() - timedelta(days=3)
    sprint.completed_at = None

    t1 = MagicMock(status="done")
    t2 = MagicMock(status="done")
    t3 = MagicMock(status="todo")

    mock_sc = MagicMock()
    mock_sc.scalars.return_value.all.return_value = [t1, t2, t3]
    db.execute = AsyncMock(return_value=mock_sc)

    stats = await sprint_manager.get_stats(db, sprint)
    assert stats["total_tasks"] == 3
    assert stats["done_tasks"] == 2
    assert stats["completion_rate"] == pytest.approx(66.67, abs=0.1)
