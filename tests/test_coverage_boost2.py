"""Additional coverage tests targeting remaining uncovered lines."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_user(**kw):
    u = MagicMock()
    u.id = kw.get("id", uuid.uuid4())
    return u


def _make_ws(owner_id=None):
    ws = MagicMock()
    ws.id = uuid.uuid4()
    ws.owner_id = owner_id or uuid.uuid4()
    ws.is_deleted = False
    return ws


# ─── WorkspaceManager: except Exception handlers ──────────────────────────────


@pytest.mark.asyncio
async def test_invite_member_unhandled_exception():
    from app.modules.workspaces.manager import workspace_manager
    from app.modules.workspaces.schemas import WorkspaceMemberInvite

    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db = AsyncMock()
    db.get = AsyncMock(return_value=ws)
    db.scalar = AsyncMock(return_value=None)
    db.add = MagicMock()
    db.commit = AsyncMock(side_effect=RuntimeError("crash"))
    db.rollback = AsyncMock()

    with pytest.raises(RuntimeError):
        await workspace_manager.invite_workspace_member(
            db, ws.id, WorkspaceMemberInvite(email="x@y.com"), user
        )


@pytest.mark.asyncio
async def test_update_member_unhandled_exception():
    from app.modules.workspaces.manager import workspace_manager
    from app.modules.workspaces.schemas import WorkspaceMemberUpdate

    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db = AsyncMock()
    db.get = AsyncMock(return_value=ws)
    mem = MagicMock()
    db.scalar = AsyncMock(return_value=mem)
    db.commit = AsyncMock(side_effect=RuntimeError("crash"))
    db.rollback = AsyncMock()

    with pytest.raises(RuntimeError):
        await workspace_manager.update_workspace_member(
            db, ws.id, uuid.uuid4(), WorkspaceMemberUpdate(role_id=None), user
        )


@pytest.mark.asyncio
async def test_remove_member_unhandled_exception():
    from app.modules.workspaces.manager import workspace_manager

    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db = AsyncMock()
    db.get = AsyncMock(return_value=ws)
    mem = MagicMock()
    mem.is_deleted = False
    db.scalar = AsyncMock(return_value=mem)
    db.commit = AsyncMock(side_effect=RuntimeError("crash"))
    db.rollback = AsyncMock()

    with pytest.raises(RuntimeError):
        await workspace_manager.remove_workspace_member(db, ws.id, uuid.uuid4(), user)


@pytest.mark.asyncio
async def test_cancel_invitation_unhandled_exception():
    from app.modules.workspaces.manager import workspace_manager

    user = _make_user()
    ws = _make_ws(owner_id=user.id)
    db = AsyncMock()
    db.get = AsyncMock(return_value=ws)
    inv = MagicMock()
    db.scalar = AsyncMock(return_value=inv)
    db.commit = AsyncMock(side_effect=RuntimeError("crash"))
    db.rollback = AsyncMock()

    with pytest.raises(RuntimeError):
        await workspace_manager.cancel_workspace_invitation(
            db, ws.id, uuid.uuid4(), user
        )


# ─── TaskManager: update with parent deadline constraint ─────────────────────


@pytest.mark.asyncio
async def test_task_update_parent_deadline_earlier_than_subtask():
    from fastapi import HTTPException
    from app.modules.tasks.manager import task_manager
    from datetime import date, timedelta

    db = AsyncMock()
    task = MagicMock()
    task.id = uuid.uuid4()
    task.parent_task_id = None  # parent task itself
    task.sprint_id = None
    task.epic_id = None
    task.deadline = date.today() + timedelta(days=10)

    # Subtask has deadline further out than new parent deadline
    subtask_deadline = date.today() + timedelta(days=8)
    mock_sc = MagicMock()
    mock_sc.scalars.return_value.__iter__ = MagicMock(
        return_value=iter([subtask_deadline])
    )
    db.execute = AsyncMock(return_value=mock_sc)

    # New deadline is earlier than a subtask's deadline
    new_deadline = date.today() + timedelta(days=5)
    with pytest.raises(HTTPException) as exc:
        await task_manager.update(db, db_obj=task, obj_in={"deadline": new_deadline})
    assert exc.value.status_code == 400
    assert "parent_deadline" in exc.value.detail


# ─── TaskManager: update cascade sprint + epic ───────────────────────────────


@pytest.mark.asyncio
async def test_task_update_cascade_epic():
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

    new_epic_id = uuid.uuid4()
    mock_sc = MagicMock()
    mock_sc.scalars.return_value.all.return_value = []
    mock_sc.scalar_one_or_none.return_value = task
    db.execute = AsyncMock(return_value=mock_sc)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    result = await task_manager.update(
        db, db_obj=task, obj_in=TaskUpdate(epic_id=new_epic_id)
    )
    assert result == task


# ─── TaskManager: check_and_unblock_dependents with blocked task ──────────────


@pytest.mark.asyncio
async def test_check_and_unblock_dependents_with_results():
    from app.modules.tasks.manager import task_manager

    db = AsyncMock()
    dep_task = MagicMock()
    dep_task.id = uuid.uuid4()
    dep_task.status = "todo"

    call_count = 0

    def exec_side(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_sc = MagicMock()
        if call_count == 1:
            mock_sc.scalars.return_value.all.return_value = [dep_task]
        else:
            # is_blocked check - still has unfinished deps
            mock_sc.scalar.return_value = str(uuid.uuid4())
        return mock_sc

    db.execute = AsyncMock(side_effect=exec_side)

    result = await task_manager.check_and_unblock_dependents(db, uuid.uuid4())
    assert result == []


@pytest.mark.asyncio
async def test_check_and_unblock_dependents_unblocked():
    from app.modules.tasks.manager import task_manager

    db = AsyncMock()
    dep_task = MagicMock()
    dep_task.id = uuid.uuid4()
    dep_task.status = "todo"

    call_count = 0

    def exec_side(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_sc = MagicMock()
        if call_count == 1:
            mock_sc.scalars.return_value.all.return_value = [dep_task]
        else:
            # No remaining blocked deps
            mock_sc.scalar.return_value = None
        return mock_sc

    db.execute = AsyncMock(side_effect=exec_side)

    result = await task_manager.check_and_unblock_dependents(db, uuid.uuid4())
    assert dep_task in result


# ─── TaskManager: get_impacted_descendants + cascade_deadlines ───────────────


@pytest.mark.asyncio
async def test_get_impacted_descendants_with_results():
    from app.modules.tasks.manager import task_manager

    db = AsyncMock()
    task_id = uuid.uuid4()
    descendant_id = str(uuid.uuid4())

    task_obj = MagicMock()
    task_obj.deadline = None

    call_count = 0

    def exec_side(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_res = MagicMock()
        if call_count == 1:
            # Raw CTE result with rows
            mock_res.all.return_value = [(descendant_id,)]
        else:
            mock_res.scalars.return_value.all.return_value = [task_obj]
        return mock_res

    db.execute = AsyncMock(side_effect=exec_side)

    result = await task_manager.get_impacted_descendants(db, task_id)
    assert task_obj in result


@pytest.mark.asyncio
async def test_cascade_deadlines_with_descendants():
    from app.modules.tasks.manager import task_manager
    from datetime import date
    from unittest.mock import patch

    db = AsyncMock()
    t1 = MagicMock()
    t1.deadline = date.today()

    with patch.object(
        task_manager, "get_impacted_descendants", new=AsyncMock(return_value=[t1])
    ):
        count = await task_manager.cascade_deadlines(db, uuid.uuid4(), delta_days=3)

    assert count == 1


@pytest.mark.asyncio
async def test_cascade_deadlines_no_descendants():
    from app.modules.tasks.manager import task_manager
    from unittest.mock import patch

    db = AsyncMock()
    with patch.object(
        task_manager, "get_impacted_descendants", new=AsyncMock(return_value=[])
    ):
        count = await task_manager.cascade_deadlines(db, uuid.uuid4(), delta_days=5)

    assert count == 0


# ─── TaskManager: add_dependency ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_dependency_success():
    from app.modules.tasks.manager import task_manager
    from unittest.mock import patch

    db = AsyncMock()
    task = MagicMock()
    task.id = uuid.uuid4()
    depends_on_id = uuid.uuid4()
    db.add = MagicMock()

    with patch.object(
        task_manager, "check_circular_dependency", new=AsyncMock(return_value=False)
    ):
        await task_manager.add_dependency(db, task, depends_on_id)

    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_add_dependency_self_dependency():
    from fastapi import HTTPException
    from app.modules.tasks.manager import task_manager

    db = AsyncMock()
    task = MagicMock()
    task.id = uuid.uuid4()

    with pytest.raises(HTTPException) as exc:
        await task_manager.add_dependency(db, task, task.id)
    assert exc.value.status_code == 400
    assert "self_dependency" in exc.value.detail


@pytest.mark.asyncio
async def test_add_dependency_circular():
    from fastapi import HTTPException
    from app.modules.tasks.manager import task_manager
    from unittest.mock import patch

    db = AsyncMock()
    task = MagicMock()
    task.id = uuid.uuid4()

    with patch.object(
        task_manager, "check_circular_dependency", new=AsyncMock(return_value=True)
    ):
        with pytest.raises(HTTPException) as exc:
            await task_manager.add_dependency(db, task, uuid.uuid4())
    assert exc.value.status_code == 400


# ─── TaskManager: assign_task ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assign_task_not_member():
    from fastapi import HTTPException
    from app.modules.tasks.manager import task_manager

    db = AsyncMock()
    task = MagicMock()
    task.project_id = uuid.uuid4()

    mock_sc = MagicMock()
    mock_sc.scalars.return_value.first.return_value = None
    db.execute = AsyncMock(return_value=mock_sc)

    with pytest.raises(HTTPException) as exc:
        await task_manager.assign_task(db, task, uuid.uuid4())
    assert exc.value.status_code == 400


# ─── TaskManager: update_position with status change ─────────────────────────


@pytest.mark.asyncio
async def test_update_position_status_change():
    from app.modules.tasks.manager import task_manager
    from unittest.mock import patch

    db = AsyncMock()
    task = MagicMock()
    task.id = uuid.uuid4()
    task.project_id = uuid.uuid4()
    task.status = "todo"  # current
    task.position = 1

    other = MagicMock()
    other.id = uuid.uuid4()
    other.position = 2

    mock_sc = MagicMock()
    mock_sc.scalars.return_value.all.return_value = [other]
    db.execute = AsyncMock(return_value=mock_sc)

    with patch.object(task_manager, "update_status", new=AsyncMock()) as mock_us:
        await task_manager.update_position(db, task, "in_progress")

    mock_us.assert_called_once()
