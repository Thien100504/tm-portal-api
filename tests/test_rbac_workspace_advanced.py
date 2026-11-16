"""Advanced tests for RBACManager and WorkspaceManager member management."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.workspaces.schemas import WorkspaceMemberInvite, WorkspaceMemberUpdate


def _make_user(owner_of_ws=False):
    u = MagicMock()
    u.id = uuid.uuid4()
    u.email = "user@test.com"
    return u


def _make_ws(owner_id=None):
    ws = MagicMock()
    ws.id = uuid.uuid4()
    ws.owner_id = owner_id or uuid.uuid4()
    ws.is_deleted = False
    return ws


# ─── RBACManager.get_user_permissions ────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_user_permissions_no_membership():
    from app.modules.rbac.manager import rbac_manager

    db = AsyncMock()
    ws_id = uuid.uuid4()
    user_id = uuid.uuid4()

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = None  # no workspace member
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result

    perms = await rbac_manager.get_user_permissions(db, user_id, ws_id)
    assert perms == set()


@pytest.mark.asyncio
async def test_get_user_permissions_with_ws_role():
    from app.modules.rbac.manager import rbac_manager

    db = AsyncMock()
    ws_id = uuid.uuid4()
    user_id = uuid.uuid4()

    mock_perm = MagicMock()
    mock_perm.code = "task.create"
    mock_role = MagicMock()
    mock_role.is_deleted = False
    mock_role.permissions = [mock_perm]
    mock_ws_member = MagicMock()
    mock_ws_member.role = mock_role

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_ws_member
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result

    perms = await rbac_manager.get_user_permissions(db, user_id, ws_id)
    assert "task.create" in perms


@pytest.mark.asyncio
async def test_get_user_permissions_with_project_role():
    from app.modules.rbac.manager import rbac_manager

    db = AsyncMock()
    ws_id = uuid.uuid4()
    user_id = uuid.uuid4()
    project_id = uuid.uuid4()

    ws_perm = MagicMock()
    ws_perm.code = "ws.view"
    ws_role = MagicMock()
    ws_role.is_deleted = False
    ws_role.permissions = [ws_perm]
    ws_member = MagicMock()
    ws_member.role = ws_role

    prj_perm = MagicMock()
    prj_perm.code = "task.create"
    prj_role = MagicMock()
    prj_role.is_deleted = False
    prj_role.permissions = [prj_perm]
    prj_member = MagicMock()
    prj_member.role = prj_role

    call_count = 0

    def exec_side(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_scalars = MagicMock()
        if call_count == 1:
            mock_scalars.first.return_value = ws_member
        else:
            mock_scalars.first.return_value = prj_member
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        return mock_result

    db.execute = AsyncMock(side_effect=exec_side)

    perms = await rbac_manager.get_user_permissions(db, user_id, ws_id, project_id)
    assert "ws.view" in perms
    assert "task.create" in perms


@pytest.mark.asyncio
async def test_get_user_permissions_deleted_role():
    from app.modules.rbac.manager import rbac_manager

    db = AsyncMock()
    mock_role = MagicMock()
    mock_role.is_deleted = True  # deleted role → no permissions
    mock_role.permissions = [MagicMock(code="task.create")]
    mock_ws_member = MagicMock()
    mock_ws_member.role = mock_role

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_ws_member
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result

    perms = await rbac_manager.get_user_permissions(db, uuid.uuid4(), uuid.uuid4())
    assert perms == set()


# ─── RBACManager.update_role_permissions ────────────────────────────────────


@pytest.mark.asyncio
async def test_update_role_permissions_not_found():
    from fastapi import HTTPException
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleUpdatePermissions

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    user = MagicMock()

    with pytest.raises(HTTPException) as exc:
        await rbac_manager.update_role_permissions(
            db, uuid.uuid4(), RoleUpdatePermissions(permission_ids=[]), user
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_role_permissions_system_role():
    from fastapi import HTTPException
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleUpdatePermissions

    db = AsyncMock()
    mock_role = MagicMock()
    mock_role.is_system_default = True
    db.scalar = AsyncMock(return_value=mock_role)
    user = MagicMock()

    with pytest.raises(HTTPException) as exc:
        await rbac_manager.update_role_permissions(
            db, uuid.uuid4(), RoleUpdatePermissions(permission_ids=[]), user
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_update_role_permissions_success():
    from app.modules.rbac.manager import rbac_manager
    from app.modules.rbac.schemas import RoleUpdatePermissions

    db = AsyncMock()
    mock_role = MagicMock()
    mock_role.is_system_default = False
    mock_role.workspace_id = None
    mock_role.permissions = []
    db.scalar = AsyncMock(return_value=mock_role)

    db.commit = AsyncMock()

    mock_role_updated = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_role_updated
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    perm_id = uuid.uuid4()
    mock_perm = MagicMock()
    mock_perm.id = perm_id
    mock_all_perms_scalars = MagicMock()
    mock_all_perms_scalars.all.return_value = [mock_perm]
    mock_all_perms_result = MagicMock()
    mock_all_perms_result.scalars.return_value = mock_all_perms_scalars

    call_count = 0

    def exec_side(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return mock_all_perms_result
        return mock_result

    db.execute = AsyncMock(side_effect=exec_side)
    user = MagicMock()
    user.id = uuid.uuid4()
    user.system_role = "admin"  # global roles: system admins only

    await rbac_manager.update_role_permissions(
        db, uuid.uuid4(), RoleUpdatePermissions(permission_ids=[perm_id]), user
    )


# ─── WorkspaceManager.invite_member ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_invite_member_user_not_registered():
    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db.get = AsyncMock(return_value=ws)

    # User not found in DB
    call_count = 0

    def scalar_side(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return None  # user not found

    db.scalar = AsyncMock(side_effect=scalar_side)
    db.add = MagicMock()
    db.commit = AsyncMock()

    invite_in = WorkspaceMemberInvite(email="newuser@example.com")
    result = await workspace_manager.invite_workspace_member(db, ws.id, invite_in, user)
    assert result["status"] == "success"
    db.add.assert_called_once()  # invitation record


@pytest.mark.asyncio
async def test_invite_member_user_exists_not_member():
    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db.get = AsyncMock(return_value=ws)

    invited_user = MagicMock()
    invited_user.id = uuid.uuid4()

    # First scalar: the invited user; second scalar: no existing membership
    call_count = 0

    def scalar_side(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return invited_user
        return None  # no membership

    db.scalar = AsyncMock(side_effect=scalar_side)
    db.add = MagicMock()
    db.commit = AsyncMock()

    invite_in = WorkspaceMemberInvite(email="existing@example.com")
    result = await workspace_manager.invite_workspace_member(db, ws.id, invite_in, user)
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_invite_member_already_member():
    from fastapi import HTTPException
    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db.get = AsyncMock(return_value=ws)

    invited_user = MagicMock()
    invited_user.id = uuid.uuid4()

    existing_mem = MagicMock()
    existing_mem.is_deleted = False

    call_count = 0

    def scalar_side(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return invited_user
        return existing_mem

    db.scalar = AsyncMock(side_effect=scalar_side)

    invite_in = WorkspaceMemberInvite(email="already@example.com")
    with pytest.raises(HTTPException) as exc:
        await workspace_manager.invite_workspace_member(db, ws.id, invite_in, user)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_invite_member_reinstates_deleted():
    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db.get = AsyncMock(return_value=ws)

    invited_user = MagicMock()
    invited_user.id = uuid.uuid4()

    deleted_mem = MagicMock()
    deleted_mem.is_deleted = True
    deleted_mem.role_id = None

    call_count = 0

    def scalar_side(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return invited_user
        return deleted_mem

    db.scalar = AsyncMock(side_effect=scalar_side)
    db.commit = AsyncMock()

    invite_in = WorkspaceMemberInvite(email="reinstated@example.com")
    await workspace_manager.invite_workspace_member(db, ws.id, invite_in, user)
    assert deleted_mem.is_deleted is False


# ─── WorkspaceManager.update_workspace_member ────────────────────────────────


@pytest.mark.asyncio
async def test_update_workspace_member_not_found():
    from fastapi import HTTPException
    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db.get = AsyncMock(return_value=ws)
    db.scalar = AsyncMock(return_value=None)

    member_in = WorkspaceMemberUpdate(role_id=uuid.uuid4())
    with pytest.raises(HTTPException) as exc:
        await workspace_manager.update_workspace_member(
            db, ws.id, uuid.uuid4(), member_in, user
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_workspace_member_success():
    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db.get = AsyncMock(return_value=ws)

    mem = MagicMock()
    mem.role_id = None
    db.scalar = AsyncMock(return_value=mem)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    new_role_id = uuid.uuid4()
    member_in = WorkspaceMemberUpdate(role_id=new_role_id)
    await workspace_manager.update_workspace_member(
        db, ws.id, uuid.uuid4(), member_in, user
    )
    assert mem.role_id == new_role_id


# ─── WorkspaceManager.remove_workspace_member ────────────────────────────────


@pytest.mark.asyncio
async def test_remove_workspace_member_not_found():
    from fastapi import HTTPException
    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db.get = AsyncMock(return_value=ws)
    db.scalar = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await workspace_manager.remove_workspace_member(db, ws.id, uuid.uuid4(), user)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_remove_workspace_member_success():
    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db.get = AsyncMock(return_value=ws)

    mem = MagicMock()
    mem.is_deleted = False
    db.scalar = AsyncMock(return_value=mem)
    db.commit = AsyncMock()

    await workspace_manager.remove_workspace_member(db, ws.id, uuid.uuid4(), user)
    assert mem.is_deleted is True


# ─── SprintManager.complete_sprint with next_sprint ──────────────────────────


@pytest.mark.asyncio
async def test_sprint_complete_next_sprint():
    from app.modules.sprints.manager import sprint_manager

    db = AsyncMock()
    sprint = MagicMock()
    sprint.status = "active"
    sprint.id = uuid.uuid4()
    sprint.project_id = uuid.uuid4()

    target_sprint_id = uuid.uuid4()
    incomplete_task = MagicMock()
    incomplete_task.status = "todo"
    incomplete_task.sprint_id = sprint.id

    target_sprint = MagicMock()
    target_sprint.is_deleted = False
    target_sprint.status = "planning"
    db.get = AsyncMock(return_value=target_sprint)

    call_count = 0

    def exec_side(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_scalars = MagicMock()
        if call_count <= 2:
            mock_scalars.all.return_value = [incomplete_task]
        else:
            mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        return mock_result

    db.execute = AsyncMock(side_effect=exec_side)
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    await sprint_manager.complete_sprint(db, sprint, "next_sprint", target_sprint_id)
    assert sprint.status == "completed"
    assert incomplete_task.sprint_id == target_sprint_id
