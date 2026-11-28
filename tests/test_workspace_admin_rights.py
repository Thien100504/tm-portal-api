import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.rbac.manager import rbac_manager
from app.modules.rbac.schemas import RoleUpdatePermissions

PM_PERMS = {
    "project.settings",
    "task.create",
    "task.update",
    "task.delete",
    "sprint.manage",
}


def _perm(code):
    return SimpleNamespace(id=uuid.uuid4(), code=code)


def _ws_member(*codes):
    role = SimpleNamespace(is_deleted=False, permissions=[_perm(c) for c in codes])
    return SimpleNamespace(role=role)


def _db_for_permissions(ws_member, project_member=None):
    """get_user_permissions: user lookup, workspace membership, project membership."""
    db = MagicMock()
    db.get = AsyncMock(return_value=SimpleNamespace(system_role="user"))
    ws_res, pm_res = MagicMock(), MagicMock()
    ws_res.scalars.return_value.first.return_value = ws_member
    pm_res.scalars.return_value.first.return_value = project_member
    db.execute = AsyncMock(side_effect=[ws_res, pm_res])
    return db


@pytest.mark.asyncio
async def test_workspace_admin_gets_project_manager_rights_in_any_workspace_project():
    db = _db_for_permissions(_ws_member("workspace.admin", "workspace.member_manage"))
    with (
        patch.object(rbac_manager, "_owns_project", new=AsyncMock(return_value=False)),
        patch.object(
            rbac_manager,
            "_system_role_permissions",
            new=AsyncMock(return_value=PM_PERMS),
        ) as pm,
    ):
        perms = await rbac_manager.get_user_permissions(
            db, uuid.uuid4(), uuid.uuid4(), project_id=uuid.uuid4()
        )
    pm.assert_awaited_once_with(db, "Project Manager")
    assert "project.settings" in perms and "workspace.admin" in perms


@pytest.mark.asyncio
async def test_plain_workspace_member_gets_no_project_rights_without_membership():
    db = _db_for_permissions(_ws_member())
    with (
        patch.object(rbac_manager, "_owns_project", new=AsyncMock(return_value=False)),
        patch.object(
            rbac_manager,
            "_system_role_permissions",
            new=AsyncMock(return_value=PM_PERMS),
        ) as pm,
    ):
        perms = await rbac_manager.get_user_permissions(
            db, uuid.uuid4(), uuid.uuid4(), project_id=uuid.uuid4()
        )
    pm.assert_not_awaited()
    assert perms == set()


def _role_db(role, new_codes):
    db = MagicMock()
    db.scalar = AsyncMock(return_value=role)
    res = MagicMock()
    res.scalars.return_value.all.return_value = [_perm(c) for c in new_codes]
    db.execute = AsyncMock(return_value=res)
    db.commit = AsyncMock()
    return db


def _role(*codes):
    return SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        is_system_default=False,
        permissions=[_perm(c) for c in codes],
    )


async def _update(role, new_codes, holds):
    db = _role_db(role, new_codes)
    ids = [uuid.uuid4() for _ in new_codes]
    with (
        patch.object(rbac_manager, "_require_role_admin", new=AsyncMock()),
        patch.object(
            rbac_manager,
            "_holds_role_without_owning",
            new=AsyncMock(return_value=holds),
        ),
    ):
        await rbac_manager.update_role_permissions(
            db,
            role.id,
            RoleUpdatePermissions(permission_ids=ids),
            SimpleNamespace(id=uuid.uuid4()),
        )
    return db


@pytest.mark.asyncio
async def test_admin_cannot_remove_admin_from_their_own_role():
    role = _role("workspace.admin", "workspace.member_manage")
    with pytest.raises(HTTPException) as exc:
        await _update(role, ["workspace.member_manage"], holds=True)
    assert exc.value.detail == "rbac.cannot_remove_own_admin"
    assert {p.code for p in role.permissions} == {
        "workspace.admin",
        "workspace.member_manage",
    }


@pytest.mark.asyncio
async def test_owner_or_other_admin_can_remove_admin_from_a_role():
    role = _role("workspace.admin", "workspace.member_manage")
    db = await _update(role, ["workspace.member_manage"], holds=False)
    db.commit.assert_awaited_once()
    assert {p.code for p in role.permissions} == {"workspace.member_manage"}


@pytest.mark.asyncio
async def test_admin_can_change_other_permissions_of_their_own_role():
    role = _role("workspace.admin", "workspace.member_manage")
    db = await _update(role, ["workspace.admin"], holds=True)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_cannot_delete_their_own_role():
    role = _role("workspace.admin")
    role.is_deleted = False
    db = MagicMock()
    db.scalar = AsyncMock(return_value=role)
    db.commit = AsyncMock()
    with (
        patch.object(rbac_manager, "_require_role_admin", new=AsyncMock()),
        patch.object(
            rbac_manager, "_holds_role_without_owning", new=AsyncMock(return_value=True)
        ),
        pytest.raises(HTTPException) as exc,
    ):
        await rbac_manager.delete_role(db, role.id, SimpleNamespace(id=uuid.uuid4()))
    assert exc.value.detail == "rbac.cannot_delete_own_role"
    assert role.is_deleted is False
