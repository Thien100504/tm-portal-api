"""Tests for the RBAC scope rules: workspace comes from the project, removed members
lose their permissions, and global roles are managed by system admins only."""

import importlib
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.rbac.manager import rbac_manager
from app.modules.rbac.schemas import RoleCreate, RoleUpdate, RoleUpdatePermissions

rbac_router = importlib.import_module("app.modules.rbac.router")


def _user(role="user"):
    u = MagicMock()
    u.id = uuid.uuid4()
    u.system_role = role
    return u


def _global_role():
    role = MagicMock()
    role.id = uuid.uuid4()
    role.is_system_default = False
    role.workspace_id = None
    return role


# ── workspace resolution ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_resolve_workspace_uses_the_project_workspace():
    ws_a = uuid.uuid4()
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=ws_a)
    assert await rbac_manager.resolve_workspace(db, None, uuid.uuid4()) == ws_a
    assert await rbac_manager.resolve_workspace(db, ws_a, uuid.uuid4()) == ws_a


@pytest.mark.asyncio
async def test_resolve_workspace_rejects_a_foreign_workspace():
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=uuid.uuid4())  # the project's real workspace (B)
    assert await rbac_manager.resolve_workspace(db, uuid.uuid4(), uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_resolve_workspace_unknown_project():
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    assert await rbac_manager.resolve_workspace(db, None, uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_resolve_workspace_without_project_keeps_workspace():
    ws = uuid.uuid4()
    assert await rbac_manager.resolve_workspace(AsyncMock(), ws, None) == ws


@pytest.mark.asyncio
async def test_check_permission_denies_cross_workspace_project():
    """Admin of workspace A must not get permissions on a project of workspace B."""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=uuid.uuid4())  # project belongs to workspace B
    with patch.object(
        rbac_manager,
        "get_user_permissions",
        new=AsyncMock(return_value={"task.delete"}),
    ) as perms:
        allowed = await rbac_manager.check_permission(
            db,
            uuid.uuid4(),
            "task.delete",
            workspace_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
        )
    assert allowed is False
    perms.assert_not_awaited()


@pytest.mark.asyncio
async def test_my_permissions_cross_workspace_returns_nothing():
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=uuid.uuid4())
    result = await rbac_router.get_my_permissions(
        project_id=uuid.uuid4(), workspace_id=uuid.uuid4(), db=db, current_user=_user()
    )
    assert result == []


# ── removed project members ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_project_permissions_ignore_removed_members():
    statements = []
    empty = MagicMock()
    empty.scalars.return_value.first.return_value = None

    async def execute(stmt):
        statements.append(str(stmt))
        return empty

    db = AsyncMock()
    db.execute = execute
    await rbac_manager.get_user_permissions(
        db, uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    )
    project_query = next(s for s in statements if "project_members" in s)
    assert "project_members.is_deleted" in project_query


# ── global roles ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_regular_user_cannot_create_global_role():
    with pytest.raises(HTTPException) as exc:
        await rbac_manager.create_role(
            AsyncMock(), RoleCreate(name="x", workspace_id=None), _user()
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_system_admin_can_create_global_role():
    created = MagicMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = created
    db = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock(return_value=result)
    assert (
        await rbac_manager.create_role(db, RoleCreate(name="x"), _user("admin"))
        is created
    )


@pytest.mark.asyncio
async def test_regular_user_cannot_update_global_role():
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=_global_role())
    with pytest.raises(HTTPException) as exc:
        await rbac_manager.update_role(db, uuid.uuid4(), RoleUpdate(name="x"), _user())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_regular_user_cannot_grant_permissions_to_global_role():
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=_global_role())
    with pytest.raises(HTTPException) as exc:
        await rbac_manager.update_role_permissions(
            db,
            uuid.uuid4(),
            RoleUpdatePermissions(permission_ids=[uuid.uuid4()]),
            _user(),
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_regular_user_cannot_delete_global_role():
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=_global_role())
    with pytest.raises(HTTPException) as exc:
        await rbac_manager.delete_role(db, uuid.uuid4(), _user())
    assert exc.value.status_code == 403


def test_role_scope_is_validated():
    with pytest.raises(ValidationError):
        RoleCreate(name="x", scope="system")
    assert RoleCreate(name="x", scope="workspace").scope == "workspace"
