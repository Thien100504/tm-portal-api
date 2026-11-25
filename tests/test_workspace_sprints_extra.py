"""Additional tests for WorkspaceManager and SprintManager."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from app.modules.workspaces.schemas import WorkspaceUpdate


def _make_user(**kw):
    u = MagicMock()
    u.id = kw.get("id", uuid.uuid4())
    return u


def _make_workspace(owner_id=None):
    ws = MagicMock()
    ws.id = uuid.uuid4()
    ws.owner_id = owner_id or uuid.uuid4()
    ws.name = "My Workspace"
    ws.type = "personal"
    ws.is_deleted = False
    return ws


def _make_sprint(status="planning"):
    s = MagicMock()
    s.id = uuid.uuid4()
    s.project_id = uuid.uuid4()
    s.status = status
    s.is_deleted = False
    s.started_at = None
    s.completed_at = None
    return s


# ─── WorkspaceManager.update_workspace ──────────────────────────────────────


@pytest.mark.asyncio
async def test_update_workspace_name():
    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    user = _make_user()
    ws = _make_workspace(owner_id=user.id)
    db.get = AsyncMock(return_value=ws)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    ws_in = WorkspaceUpdate(name="New Name")
    await workspace_manager.update_workspace(db, ws.id, ws_in, user)
    assert ws.name == "New Name"


@pytest.mark.asyncio
async def test_update_workspace_integrity_error():
    from fastapi import HTTPException

    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    user = _make_user()
    ws = _make_workspace(owner_id=user.id)
    db.get = AsyncMock(return_value=ws)
    db.commit = AsyncMock(side_effect=IntegrityError("dup", None, None))
    db.rollback = AsyncMock()

    ws_in = WorkspaceUpdate(name="Dup Name")
    with pytest.raises(HTTPException) as exc:
        await workspace_manager.update_workspace(db, ws.id, ws_in, user)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_workspace_operational_error():
    from fastapi import HTTPException

    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    user = _make_user()
    ws = _make_workspace(owner_id=user.id)
    db.get = AsyncMock(return_value=ws)
    db.commit = AsyncMock(side_effect=OperationalError("db down", None, None))
    db.rollback = AsyncMock()

    ws_in = WorkspaceUpdate(name="Fail")
    with pytest.raises(HTTPException) as exc:
        await workspace_manager.update_workspace(db, ws.id, ws_in, user)
    assert exc.value.status_code == 503


# ─── WorkspaceManager.delete_workspace ──────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_workspace_success():
    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    user = _make_user()
    ws = _make_workspace(owner_id=user.id)
    db.get = AsyncMock(return_value=ws)
    db.delete = AsyncMock()
    db.scalar = AsyncMock(
        side_effect=[0, 2]
    )  # no live projects, two personal workspaces
    db.commit = AsyncMock()

    await workspace_manager.delete_workspace(db, ws.id, user)
    db.delete.assert_called_once_with(ws)
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_delete_workspace_integrity_error():
    from fastapi import HTTPException

    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    user = _make_user()
    ws = _make_workspace(owner_id=user.id)
    db.get = AsyncMock(return_value=ws)
    db.delete = AsyncMock()
    db.scalar = AsyncMock(
        side_effect=[0, 2]
    )  # no live projects, two personal workspaces
    db.commit = AsyncMock(side_effect=IntegrityError("ref", None, None))
    db.rollback = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await workspace_manager.delete_workspace(db, ws.id, user)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_delete_workspace_operational_error():
    from fastapi import HTTPException

    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    user = _make_user()
    ws = _make_workspace(owner_id=user.id)
    db.get = AsyncMock(return_value=ws)
    db.delete = AsyncMock()
    db.scalar = AsyncMock(
        side_effect=[0, 2]
    )  # no live projects, two personal workspaces
    db.commit = AsyncMock(side_effect=OperationalError("db", None, None))
    db.rollback = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await workspace_manager.delete_workspace(db, ws.id, user)
    assert exc.value.status_code == 503


# ─── WorkspaceManager.get_workspace_members ─────────────────────────────────


@pytest.mark.asyncio
async def test_get_workspace_members():
    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    user = _make_user()
    ws = _make_workspace(owner_id=user.id)
    db.get = AsyncMock(return_value=ws)

    members = [MagicMock(), MagicMock()]

    call_count = 0

    def exec_side(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = members
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_result.scalar_one_or_none.return_value = MagicMock()
        return mock_result

    db.execute = AsyncMock(side_effect=exec_side)

    result = await workspace_manager.get_workspace_members(db, ws.id, user)
    assert len(result) == 2


# ─── WorkspaceManager.get_workspace_invitations ──────────────────────────────


@pytest.mark.asyncio
async def test_get_workspace_invitations():
    from app.modules.workspaces.manager import workspace_manager

    db = AsyncMock()
    user = _make_user()
    ws = _make_workspace(owner_id=user.id)
    db.get = AsyncMock(return_value=ws)

    invites = [MagicMock()]
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = invites
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result

    result = await workspace_manager.get_workspace_invitations(db, ws.id, user)
    assert len(result) == 1


# ─── SprintManager additional methods ────────────────────────────────────────


@pytest.mark.asyncio
async def test_sprint_reopen_not_completed():
    from fastapi import HTTPException

    from app.modules.sprints.manager import sprint_manager

    db = AsyncMock()
    sprint = _make_sprint(status="active")

    with pytest.raises(HTTPException) as exc:
        await sprint_manager.reopen_sprint(db, sprint)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_sprint_reopen_already_active_exists():
    from fastapi import HTTPException

    from app.modules.sprints.manager import sprint_manager

    db = AsyncMock()
    sprint = _make_sprint(status="completed")
    existing_active = _make_sprint(status="active")

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = existing_active
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc:
        await sprint_manager.reopen_sprint(db, sprint)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_sprint_reopen_success():
    from app.modules.sprints.manager import sprint_manager

    db = AsyncMock()
    sprint = _make_sprint(status="completed")
    sprint.completed_at = MagicMock()

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = None
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    await sprint_manager.reopen_sprint(db, sprint)
    assert sprint.status == "active"
    assert sprint.completed_at is None


@pytest.mark.asyncio
async def test_sprint_get_stats_no_tasks():
    from app.modules.sprints.manager import sprint_manager

    db = AsyncMock()
    sprint = _make_sprint(status="active")

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result

    stats = await sprint_manager.get_stats(db, sprint)
    assert stats["total_tasks"] == 0
    assert stats["completion_rate"] == 0.0


@pytest.mark.asyncio
async def test_sprint_get_stats_with_tasks():
    from app.modules.sprints.manager import sprint_manager

    db = AsyncMock()
    sprint = _make_sprint(status="active")
    sprint.started_at = None

    task_done = MagicMock(status="done")
    task_todo = MagicMock(status="todo")

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [task_done, task_todo]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result

    stats = await sprint_manager.get_stats(db, sprint)
    assert stats["total_tasks"] == 2
    assert stats["done_tasks"] == 1
    assert stats["completion_rate"] == 50.0


# ─── ProjectManager.create_project_with_owner ────────────────────────────────


@pytest.mark.asyncio
async def test_create_project_with_owner():
    from app.modules.projects.manager import project_manager
    from app.modules.projects.schemas import ProjectCreate

    db = AsyncMock()
    owner_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    obj_in = ProjectCreate(name="Test Project", workspace_id=workspace_id)

    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    mock_role = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_role
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result

    await project_manager.create_project_with_owner(db, obj_in, owner_id)
    db.add.assert_called()


@pytest.mark.asyncio
async def test_create_project_auto_workspace():
    from app.modules.projects.manager import project_manager
    from app.modules.projects.schemas import ProjectCreate

    db = AsyncMock()
    owner_id = uuid.uuid4()

    obj_in = ProjectCreate(name="Test Project")  # no workspace_id

    mock_ws = MagicMock()
    mock_ws.id = uuid.uuid4()

    call_count = 0

    def get_side(model, id_val):
        nonlocal call_count
        call_count += 1
        return mock_ws

    db.get = AsyncMock(side_effect=get_side)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    mock_role = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = mock_role
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result

    await project_manager.create_project_with_owner(db, obj_in, owner_id)
    db.add.assert_called()


# ─── ProjectManager.add_member ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_member_success():
    from app.modules.projects.manager import project_manager

    db = AsyncMock()
    new_member = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = new_member
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.scalar = AsyncMock(return_value=None)  # not a former member

    result = await project_manager.add_member(
        db, uuid.uuid4(), uuid.uuid4(), "member", role_id=uuid.uuid4()
    )
    db.add.assert_called_once()
    assert result == new_member


@pytest.mark.asyncio
async def test_get_all_members():
    from app.modules.projects.manager import project_manager

    db = AsyncMock()
    members = [MagicMock(), MagicMock(), MagicMock()]
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = members
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result

    result = await project_manager.get_all_members(db, uuid.uuid4())
    assert len(result) == 3
