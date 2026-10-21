"""Unit tests for various managers with mocked AsyncSession."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _exec_scalars(db: AsyncMock, first=None, all_items=None):
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = first
    mock_scalars.all.return_value = all_items if all_items is not None else []
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result
    return mock_result


def _make_user(**kwargs):
    u = MagicMock()
    u.id = kwargs.get("id", uuid.uuid4())
    u.email = kwargs.get("email", "user@example.com")
    u.full_name = kwargs.get("full_name", "Test User")
    u.is_active = kwargs.get("is_active", True)
    u.password_hash = kwargs.get("password_hash", "hashed")
    u.system_role = kwargs.get("system_role", "user")
    return u


def _make_sprint(**kwargs):
    s = MagicMock()
    s.id = kwargs.get("id", uuid.uuid4())
    s.project_id = kwargs.get("project_id", uuid.uuid4())
    s.status = kwargs.get("status", "planning")
    s.is_deleted = False
    s.name = kwargs.get("name", "Sprint 1")
    s.started_at = None
    s.completed_at = None
    return s


# ─── UserManager ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_manager_get_by_email_found():
    from app.modules.auth.manager import user_manager

    db = AsyncMock()
    user = _make_user()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    db.execute.return_value = mock_result

    result = await user_manager.get_by_email(db, "user@example.com")
    assert result == user


@pytest.mark.asyncio
async def test_user_manager_get_by_email_not_found():
    from app.modules.auth.manager import user_manager

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute.return_value = mock_result

    result = await user_manager.get_by_email(db, "nobody@example.com")
    assert result is None


@pytest.mark.asyncio
async def test_user_manager_search_users():
    from app.modules.auth.manager import user_manager

    db = AsyncMock()
    users = [_make_user(), _make_user()]
    _exec_scalars(db, all_items=users)

    result = await user_manager.search_users(db, "test")
    assert len(result) == 2


@pytest.mark.asyncio
async def test_user_manager_update_with_password():
    from app.modules.auth.manager import user_manager

    db = AsyncMock()
    user = _make_user()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    result = await user_manager.update(db, db_obj=user, obj_in={"password": "NewPass1"})
    # password should be hashed, not stored as plain text
    assert result == user


@pytest.mark.asyncio
async def test_user_manager_update_without_password():
    from app.modules.auth.manager import user_manager
    from app.modules.auth.schemas import UserUpdate

    db = AsyncMock()
    user = _make_user()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    result = await user_manager.update(
        db, db_obj=user, obj_in=UserUpdate(full_name="New Name")
    )
    assert result == user


# ─── SprintManager ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sprint_get_by_project():
    from app.modules.sprints.manager import sprint_manager

    db = AsyncMock()
    sprints = [_make_sprint(), _make_sprint()]
    _exec_scalars(db, all_items=sprints)

    result = await sprint_manager.get_sprints_by_project(db, uuid.uuid4())
    assert len(result) == 2


@pytest.mark.asyncio
async def test_sprint_start_not_in_planning():
    from fastapi import HTTPException
    from app.modules.sprints.manager import sprint_manager

    db = AsyncMock()
    sprint = _make_sprint(status="active")

    with pytest.raises(HTTPException) as exc:
        await sprint_manager.start_sprint(db, sprint)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_sprint_start_already_active():
    from fastapi import HTTPException
    from app.modules.sprints.manager import sprint_manager

    db = AsyncMock()
    sprint = _make_sprint(status="planning")
    existing_active = _make_sprint(status="active")
    _exec_scalars(db, first=existing_active)

    with pytest.raises(HTTPException) as exc:
        await sprint_manager.start_sprint(db, sprint)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_sprint_start_success():
    from app.modules.sprints.manager import sprint_manager

    db = AsyncMock()
    sprint = _make_sprint(status="planning")
    _exec_scalars(db, first=None)  # no existing active sprint

    await sprint_manager.start_sprint(db, sprint)
    assert sprint.status == "active"
    assert sprint.started_at is not None


# ─── BaseManager CRUD ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_base_manager_get():
    from app.modules.auth.manager import user_manager

    db = AsyncMock()
    user = _make_user()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    db.execute.return_value = mock_result

    result = await user_manager.get(db, user.id)
    assert result == user


@pytest.mark.asyncio
async def test_base_manager_get_multi():
    from app.modules.auth.manager import user_manager

    db = AsyncMock()
    users = [_make_user(), _make_user(), _make_user()]
    _exec_scalars(db, all_items=users)

    result = await user_manager.get_multi(db, skip=0, limit=10)
    assert len(result) == 3


@pytest.mark.asyncio
async def test_base_manager_remove_found():
    from app.modules.auth.manager import user_manager

    db = AsyncMock()
    user = _make_user()
    db.get = AsyncMock(return_value=user)
    db.delete = AsyncMock()
    db.flush = AsyncMock()

    result = await user_manager.remove(db, id=user.id)
    assert result == user
    db.delete.assert_called_once_with(user)


@pytest.mark.asyncio
async def test_base_manager_remove_not_found():
    from app.modules.auth.manager import user_manager

    db = AsyncMock()
    db.get = AsyncMock(return_value=None)

    result = await user_manager.remove(db, id=uuid.uuid4())
    assert result is None


# ─── DashboardManager ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dashboard_admin_stats_forbidden():
    from fastapi import HTTPException
    from app.modules.dashboard.manager import dashboard_manager

    db = AsyncMock()
    non_admin = _make_user(system_role="user")

    with pytest.raises(HTTPException) as exc:
        await dashboard_manager.get_admin_stats(db, non_admin)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_dashboard_admin_stats_success():
    from app.modules.dashboard.manager import dashboard_manager

    db = AsyncMock()
    admin = _make_user(system_role="admin")

    db.scalar = AsyncMock(return_value=10)

    recent_users = [_make_user(), _make_user()]
    _exec_scalars(db, all_items=recent_users)

    result = await dashboard_manager.get_admin_stats(db, admin)
    assert result.total_users == 10


@pytest.mark.asyncio
async def test_dashboard_personal_stats():
    from app.modules.dashboard.manager import dashboard_manager

    db = AsyncMock()
    user = _make_user()

    db.scalar = AsyncMock(return_value=3)

    call_count = 0

    def exec_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_result.all.return_value = []
        return mock_result

    db.execute = AsyncMock(side_effect=exec_side_effect)

    result = await dashboard_manager.get_personal_stats(db, user)
    assert result is not None
    assert result.overdue_count == 3


# ─── WorkspaceManager (basic) ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_workspace_list():
    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()

    call_count = 0

    def exec_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_result.all.return_value = []
        return mock_result

    db.execute = AsyncMock(side_effect=exec_side_effect)

    user = _make_user()
    result = await workspace_manager.list_workspaces(db, user)
    assert isinstance(result, list)


# ─── RBACManager ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rbac_get_roles_project_scope():
    from app.modules.rbac.manager import rbac_manager

    db = AsyncMock()
    mock_roles = [MagicMock(), MagicMock()]
    _exec_scalars(db, all_items=mock_roles)

    result = await rbac_manager.get_roles(db, scope="project")
    assert len(result) == 2


@pytest.mark.asyncio
async def test_rbac_get_roles_with_workspace():
    from app.modules.rbac.manager import rbac_manager

    db = AsyncMock()
    _exec_scalars(db, all_items=[])

    result = await rbac_manager.get_roles(
        db, scope="workspace", workspace_id=uuid.uuid4()
    )
    assert result == []


@pytest.mark.asyncio
async def test_rbac_check_permission_no_workspace():
    from app.modules.rbac.manager import rbac_manager

    db = AsyncMock()
    user_id = uuid.uuid4()
    # project exists but scalar returns None workspace_id → returns False
    db.scalar = AsyncMock(return_value=None)

    result = await rbac_manager.check_permission(
        db, user_id, "task.create", project_id=uuid.uuid4()
    )
    assert result is False


@pytest.mark.asyncio
async def test_rbac_check_permission_no_args_returns_false():
    from app.modules.rbac.manager import rbac_manager

    db = AsyncMock()
    # No workspace_id, no project_id → immediate False
    result = await rbac_manager.check_permission(db, uuid.uuid4(), "task.create")
    assert result is False
