"""Tests for WorkspaceManager and ProjectManager with mocked DB."""

import uuid
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.exc import IntegrityError, OperationalError

import pytest

from app.modules.workspaces.schemas import WorkspaceCreate


def _make_user(**kwargs):
    u = MagicMock()
    u.id = kwargs.get("id", uuid.uuid4())
    u.email = kwargs.get("email", "user@test.com")
    u.full_name = kwargs.get("full_name", "Test User")
    return u


def _make_workspace(**kwargs):
    ws = MagicMock()
    ws.id = kwargs.get("id", uuid.uuid4())
    ws.name = kwargs.get("name", "My Workspace")
    ws.type = kwargs.get("type", "personal")
    ws.owner_id = kwargs.get("owner_id", uuid.uuid4())
    ws.is_deleted = False
    return ws


def _make_project(**kwargs):
    p = MagicMock()
    p.id = kwargs.get("id", uuid.uuid4())
    p.name = kwargs.get("name", "My Project")
    p.owner_id = kwargs.get("owner_id", uuid.uuid4())
    p.workspace_id = kwargs.get("workspace_id", uuid.uuid4())
    p.is_deleted = False
    p.memberships = []
    return p


def _exec_scalars(db, first=None, all_items=None):
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = first
    mock_scalars.all.return_value = all_items if all_items is not None else []
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    mock_result.scalar_one_or_none.return_value = first
    db.execute.return_value = mock_result
    return mock_result


# ─── WorkspaceManager.create_workspace ──────────────────────────────────────


@pytest.mark.asyncio
async def test_create_workspace_team_type():
    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    user = _make_user()

    ws_in = WorkspaceCreate(name="Team WS", type="team")
    await workspace_manager.create_workspace(db, ws_in, user)

    db.add.assert_called_once()
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_create_workspace_personal_type():
    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    user = _make_user()

    ws_in = WorkspaceCreate(name="Personal WS", type="personal")
    await workspace_manager.create_workspace(db, ws_in, user)

    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_create_workspace_integrity_error():
    from fastapi import HTTPException
    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock(side_effect=IntegrityError("dup", None, None))
    db.rollback = AsyncMock()
    user = _make_user()

    ws_in = WorkspaceCreate(name="Dupe WS", type="personal")
    with pytest.raises(HTTPException) as exc:
        await workspace_manager.create_workspace(db, ws_in, user)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_workspace_operational_error():
    from fastapi import HTTPException
    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock(side_effect=OperationalError("db down", None, None))
    db.rollback = AsyncMock()
    user = _make_user()

    ws_in = WorkspaceCreate(name="Fail WS", type="personal")
    with pytest.raises(HTTPException) as exc:
        await workspace_manager.create_workspace(db, ws_in, user)
    assert exc.value.status_code == 503


# ─── WorkspaceManager.get_workspace ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_workspace_owner():
    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    user = _make_user()
    ws = _make_workspace(owner_id=user.id)
    db.get = AsyncMock(return_value=ws)

    result = await workspace_manager.get_workspace(db, ws.id, user)
    assert result == ws


@pytest.mark.asyncio
async def test_get_workspace_not_found():
    from fastapi import HTTPException
    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    user = _make_user()

    with pytest.raises(HTTPException) as exc:
        await workspace_manager.get_workspace(db, uuid.uuid4(), user)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_workspace_non_owner_member():
    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    user = _make_user()
    ws = _make_workspace(owner_id=uuid.uuid4())  # different owner
    db.get = AsyncMock(return_value=ws)

    # User IS a workspace member
    member = MagicMock()
    _exec_scalars(db, first=member)

    result = await workspace_manager.get_workspace(db, ws.id, user)
    assert result == ws


@pytest.mark.asyncio
async def test_get_workspace_non_owner_denied():
    from fastapi import HTTPException
    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    user = _make_user()
    ws = _make_workspace(owner_id=uuid.uuid4())
    db.get = AsyncMock(return_value=ws)

    # Neither workspace member nor project member
    call_count = 0

    def exec_side(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = None
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = None
        mock_res.scalars.return_value = mock_scalars
        return mock_res

    db.execute = AsyncMock(side_effect=exec_side)

    with pytest.raises(HTTPException) as exc:
        await workspace_manager.get_workspace(db, ws.id, user)
    assert exc.value.status_code == 403


# ─── WorkspaceManager._check_workspace_owner ────────────────────────────────


@pytest.mark.asyncio
async def test_check_workspace_owner_success():
    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    user = _make_user()
    ws = _make_workspace(owner_id=user.id)
    db.get = AsyncMock(return_value=ws)

    result = await workspace_manager._check_workspace_owner(db, ws.id, user.id)
    assert result == ws


@pytest.mark.asyncio
async def test_check_workspace_owner_not_found():
    from fastapi import HTTPException
    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    db.get = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await workspace_manager._check_workspace_owner(db, uuid.uuid4(), uuid.uuid4())
    assert exc.value.status_code == 404


# ─── ProjectManager.get_projects_for_user ───────────────────────────────────


@pytest.mark.asyncio
async def test_get_projects_for_user_empty():
    from app.modules.projects.manager import project_manager

    db = AsyncMock()

    call_count = 0

    def exec_side(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_result.all.return_value = []
        return mock_result

    db.execute = AsyncMock(side_effect=exec_side)

    result = await project_manager.get_projects_for_user(db, uuid.uuid4())
    assert result == []


@pytest.mark.asyncio
async def test_get_projects_for_user_with_workspace():
    from app.modules.projects.manager import project_manager

    db = AsyncMock()

    def exec_side(*args, **kwargs):
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_result.all.return_value = []
        return mock_result

    db.execute = AsyncMock(side_effect=exec_side)

    result = await project_manager.get_projects_for_user(
        db, uuid.uuid4(), workspace_id=uuid.uuid4()
    )
    assert result == []


@pytest.mark.asyncio
async def test_get_projects_for_user_with_results():
    from app.modules.projects.manager import project_manager

    db = AsyncMock()
    projects = [_make_project(), _make_project()]

    call_count = 0

    def exec_side(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_scalars = MagicMock()
        if call_count == 1:
            mock_scalars.all.return_value = projects
        else:
            mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_result.all.return_value = []
        return mock_result

    db.execute = AsyncMock(side_effect=exec_side)

    result = await project_manager.get_projects_for_user(db, uuid.uuid4())
    assert len(result) == 2


# ─── ProjectManager.get_project_for_user ────────────────────────────────────


@pytest.mark.asyncio
async def test_get_project_for_user_found():
    from app.modules.projects.manager import project_manager

    db = AsyncMock()
    project = _make_project()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = project
    mock_scalars.all.return_value = []
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result

    result = await project_manager.get_project_for_user(db, project.id, uuid.uuid4())
    assert result == project


@pytest.mark.asyncio
async def test_get_project_for_user_not_found():
    from app.modules.projects.manager import project_manager

    db = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = None
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result

    result = await project_manager.get_project_for_user(db, uuid.uuid4(), uuid.uuid4())
    assert result is None


# ─── ProjectManager.get_member ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_member_found():
    from app.modules.projects.manager import project_manager

    db = AsyncMock()
    member = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = member
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result

    result = await project_manager.get_member(db, uuid.uuid4(), uuid.uuid4())
    assert result == member


@pytest.mark.asyncio
async def test_get_member_not_found():
    from app.modules.projects.manager import project_manager

    db = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = None
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result

    result = await project_manager.get_member(db, uuid.uuid4(), uuid.uuid4())
    assert result is None


# ─── ProjectManager.get_all_members ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_all_members():
    from app.modules.projects.manager import project_manager

    db = AsyncMock()
    members = [MagicMock(), MagicMock()]
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = members
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result

    result = await project_manager.get_all_members(db, uuid.uuid4())
    assert len(result) == 2


# ─── SprintManager additional ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sprint_complete_not_active():
    from fastapi import HTTPException
    from app.modules.sprints.manager import sprint_manager

    db = AsyncMock()
    sprint = MagicMock()
    sprint.status = "planning"

    with pytest.raises(HTTPException) as exc:
        await sprint_manager.complete_sprint(db, sprint, "backlog", None)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_sprint_complete_success_backlog():
    from app.modules.sprints.manager import sprint_manager

    db = AsyncMock()
    sprint = MagicMock()
    sprint.status = "active"
    sprint.id = uuid.uuid4()
    sprint.project_id = uuid.uuid4()

    incomplete_task = MagicMock()
    incomplete_task.status = "todo"

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

    result = await sprint_manager.complete_sprint(db, sprint, "backlog", None)
    assert sprint.status == "completed"
    assert "total" in result or result is not None
