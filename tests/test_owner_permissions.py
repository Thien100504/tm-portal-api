"""Project permissions of owners and of members without a role_id."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.rbac.manager import rbac_manager

PM_PERMISSIONS = {
    "project.settings",
    "task.create",
    "task.update",
    "task.delete",
    "sprint.manage",
}


def _db(project_member, owners=(None, None)):
    """A session returning no workspace member, then the given project member."""
    results = []
    for row in (None, project_member):
        result = MagicMock()
        result.scalars.return_value.first.return_value = row
        results.append(result)
    db = MagicMock()
    db.get = AsyncMock(
        return_value=SimpleNamespace(system_role="user")
    )  # not a system admin
    db.execute = AsyncMock(side_effect=results)
    db.scalar = AsyncMock(side_effect=list(owners))
    return db


@pytest.mark.asyncio
async def test_project_creator_without_role_id_gets_project_manager_rights():
    user = uuid.uuid4()
    member = SimpleNamespace(role=None, project_role="project_manager")
    with patch.object(
        rbac_manager,
        "_system_role_permissions",
        new=AsyncMock(return_value=PM_PERMISSIONS),
    ) as roles:
        perms = await rbac_manager.get_user_permissions(
            _db(member, owners=(user,)), user, uuid.uuid4(), uuid.uuid4()
        )
    roles.assert_awaited_once()
    assert roles.await_args.args[1] == "Project Manager"
    assert "task.create" in perms


@pytest.mark.asyncio
async def test_workspace_owner_gets_project_manager_rights():
    user = uuid.uuid4()
    with patch.object(
        rbac_manager,
        "_system_role_permissions",
        new=AsyncMock(return_value=PM_PERMISSIONS),
    ):
        perms = await rbac_manager.get_user_permissions(
            _db(None, owners=(uuid.uuid4(), user)), user, uuid.uuid4(), uuid.uuid4()
        )
    assert perms == PM_PERMISSIONS


@pytest.mark.asyncio
async def test_viewer_without_role_id_stays_read_only():
    member = SimpleNamespace(role=None, project_role="viewer")
    with patch.object(
        rbac_manager, "_system_role_permissions", new=AsyncMock(return_value=set())
    ) as roles:
        perms = await rbac_manager.get_user_permissions(
            _db(member, owners=(uuid.uuid4(), uuid.uuid4())),
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
        )
    assert roles.await_args.args[1] == "Viewer"
    assert perms == set()


@pytest.mark.asyncio
async def test_non_member_gets_no_project_rights():
    with patch.object(
        rbac_manager, "_system_role_permissions", new=AsyncMock()
    ) as roles:
        perms = await rbac_manager.get_user_permissions(
            _db(None, owners=(uuid.uuid4(), uuid.uuid4())),
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
        )
    roles.assert_not_awaited()
    assert perms == set()


@pytest.mark.asyncio
async def test_assigned_role_is_not_widened_for_a_plain_member():
    role = SimpleNamespace(
        is_deleted=False, permissions=[SimpleNamespace(code="task.update")]
    )
    member = SimpleNamespace(role=role, project_role="project_manager")
    with patch.object(
        rbac_manager, "_system_role_permissions", new=AsyncMock()
    ) as roles:
        perms = await rbac_manager.get_user_permissions(
            _db(member, owners=(uuid.uuid4(), uuid.uuid4())),
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
        )
    roles.assert_not_awaited()
    assert perms == {"task.update"}
