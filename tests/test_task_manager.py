"""Unit tests for TaskManager — all DB calls mocked with AsyncMock."""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.tasks.manager import task_manager
from app.modules.tasks.schemas import TaskCreate, TaskUpdate


def _make_task(
    task_id: uuid.UUID | None = None,
    title: str = "Test Task",
    status: str = "todo",
    is_deleted: bool = False,
    parent_task_id: uuid.UUID | None = None,
    deadline: datetime | None = None,
    sprint_id: uuid.UUID | None = None,
    epic_id: uuid.UUID | None = None,
) -> MagicMock:
    task = MagicMock()
    task.id = task_id or uuid.uuid4()
    task.title = title
    task.status = status
    task.is_deleted = is_deleted
    task.parent_task_id = parent_task_id
    task.deadline = deadline
    task.sprint_id = sprint_id
    task.epic_id = epic_id
    task.position = 1
    task.project_id = uuid.uuid4()
    task.workspace_id = uuid.uuid4()
    task.subtasks = []
    task.dependencies = []
    task.dependent_tasks = []
    return task


def _mock_execute_scalars(db: AsyncMock, first=None, all_items=None):
    mock_scalars = MagicMock()
    mock_scalars.first.return_value = first
    mock_scalars.all.return_value = all_items or []
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    db.execute.return_value = mock_result
    return mock_result


# ─── get_by_id ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_by_id_returns_task():
    db = AsyncMock()
    task_id = uuid.uuid4()
    mock_task = _make_task(task_id=task_id)
    _mock_execute_scalars(db, first=mock_task)

    result = await task_manager.get_by_id(db, task_id)
    assert result == mock_task


@pytest.mark.asyncio
async def test_get_by_id_not_found():
    db = AsyncMock()
    _mock_execute_scalars(db, first=None)

    result = await task_manager.get_by_id(db, uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_get_by_id_filters_deleted_subtasks():
    db = AsyncMock()
    alive = MagicMock(is_deleted=False)
    dead = MagicMock(is_deleted=True)
    mock_task = _make_task()
    mock_task.subtasks = [alive, dead]
    _mock_execute_scalars(db, first=mock_task)

    result = await task_manager.get_by_id(db, mock_task.id)
    assert result is not None
    assert len(result.subtasks) == 1
    assert result.subtasks[0] is alive


# ─── get_tasks_by_project ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_tasks_by_project_empty():
    db = AsyncMock()
    _mock_execute_scalars(db, all_items=[])

    result = await task_manager.get_tasks_by_project(db, uuid.uuid4())
    assert result == []


@pytest.mark.asyncio
async def test_get_tasks_by_project_returns_tasks():
    db = AsyncMock()
    tasks = [_make_task(), _make_task()]
    _mock_execute_scalars(db, all_items=tasks)

    result = await task_manager.get_tasks_by_project(db, uuid.uuid4())
    assert len(result) == 2


@pytest.mark.asyncio
async def test_get_tasks_by_project_filters_deleted_subtasks():
    db = AsyncMock()
    alive = MagicMock(is_deleted=False)
    dead = MagicMock(is_deleted=True)
    task = _make_task()
    task.subtasks = [alive, dead]
    _mock_execute_scalars(db, all_items=[task])

    result = await task_manager.get_tasks_by_project(db, uuid.uuid4())
    assert len(result[0].subtasks) == 1


# ─── create_task ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_task_basic():
    db = AsyncMock()
    project_id = uuid.uuid4()
    creator_id = uuid.uuid4()
    obj_in = TaskCreate(title="New Task", project_id=project_id)

    mock_result = MagicMock()
    mock_result.scalar.return_value = 5
    db.execute.return_value = mock_result
    mock_project = MagicMock()
    mock_project.workspace_id = uuid.uuid4()
    mock_project.parent_task_id = None
    db.get.return_value = mock_project
    db.add = MagicMock()
    db.flush = AsyncMock()

    await task_manager.create_task(db, obj_in, creator_id)
    db.add.assert_called_once()
    db.flush.assert_called_once()


@pytest.mark.asyncio
async def test_create_task_no_project():
    db = AsyncMock()
    obj_in = TaskCreate(title="Task", project_id=uuid.uuid4())

    mock_result = MagicMock()
    mock_result.scalar.return_value = None
    db.execute.return_value = mock_result
    db.get.return_value = None
    db.add = MagicMock()
    db.flush = AsyncMock()

    await task_manager.create_task(db, obj_in, uuid.uuid4())
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_create_task_parent_not_found():
    from fastapi import HTTPException

    db = AsyncMock()
    parent_id = uuid.uuid4()
    obj_in = TaskCreate(
        title="Subtask", project_id=uuid.uuid4(), parent_task_id=parent_id
    )
    mock_result = MagicMock()
    mock_result.scalar.return_value = 0
    db.execute.return_value = mock_result
    db.get.return_value = None

    with pytest.raises(HTTPException) as exc:
        await task_manager.create_task(db, obj_in, uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_task_subtask_depth_limit():
    from fastapi import HTTPException

    db = AsyncMock()
    parent_id = uuid.uuid4()
    obj_in = TaskCreate(title="Deep", project_id=uuid.uuid4(), parent_task_id=parent_id)
    mock_result = MagicMock()
    mock_result.scalar.return_value = 0
    db.execute.return_value = mock_result

    mock_parent = MagicMock()
    mock_parent.parent_task_id = uuid.uuid4()  # parent itself has a parent
    db.get.return_value = mock_parent

    with pytest.raises(HTTPException) as exc:
        await task_manager.create_task(db, obj_in, uuid.uuid4())
    assert exc.value.status_code == 400


# ─── update ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_task_with_dict():
    db = AsyncMock()
    task = _make_task()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalars.return_value = iter([])
    db.execute.return_value = mock_result

    result = await task_manager.update(db, db_obj=task, obj_in={"title": "Updated"})
    assert result == task


@pytest.mark.asyncio
async def test_update_task_with_schema():
    db = AsyncMock()
    task = _make_task()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalars.return_value = iter([])
    db.execute.return_value = mock_result

    obj_in = TaskUpdate(title="Updated schema")
    result = await task_manager.update(db, db_obj=task, obj_in=obj_in)
    assert result == task


# ─── update_status ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_status_to_in_progress_no_deps():
    db = AsyncMock()
    task = _make_task(status="todo")
    _mock_execute_scalars(db, all_items=[])

    await task_manager.update_status(db, task, "in_progress")
    assert task.status == "in_progress"


@pytest.mark.asyncio
async def test_update_status_to_done_subtasks_incomplete():
    from fastapi import HTTPException

    db = AsyncMock()
    task = _make_task(status="in_progress")
    pending_sub = _make_task(status="todo")
    _mock_execute_scalars(db, all_items=[pending_sub])

    with pytest.raises(HTTPException) as exc:
        await task_manager.update_status(db, task, "done")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_update_status_to_done_no_subtasks():
    db = AsyncMock()
    task = _make_task(status="in_progress")
    _mock_execute_scalars(db, all_items=[])

    await task_manager.update_status(db, task, "done")
    assert task.status == "done"


@pytest.mark.asyncio
async def test_update_status_in_progress_blocked_by_dep():
    from fastapi import HTTPException

    db = AsyncMock()
    task = _make_task(status="todo")
    blocker = _make_task(status="in_progress")
    _mock_execute_scalars(db, all_items=[blocker])

    with pytest.raises(HTTPException) as exc:
        await task_manager.update_status(db, task, "in_progress")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_update_status_override_bypasses_dep_check():
    db = AsyncMock()
    task = _make_task(status="todo")
    _mock_execute_scalars(db, all_items=[])

    await task_manager.update_status(db, task, "in_progress", override=True)
    assert task.status == "in_progress"


# ─── add_dependency / remove_dependency ─────────────────────────────────────


@pytest.mark.asyncio
async def test_add_dependency_self_loop():
    from fastapi import HTTPException

    db = AsyncMock()
    task = _make_task()

    with pytest.raises(HTTPException) as exc:
        await task_manager.add_dependency(db, task, task.id)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_add_dependency_no_circular():
    db = AsyncMock()
    task = _make_task()
    depends_on_id = uuid.uuid4()

    mock_result = MagicMock()
    mock_result.scalar.return_value = None  # no cycle
    db.execute.return_value = mock_result
    db.add = MagicMock()

    await task_manager.add_dependency(db, task, depends_on_id)
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_add_dependency_circular():
    from fastapi import HTTPException

    db = AsyncMock()
    task = _make_task()
    depends_on_id = uuid.uuid4()

    mock_result = MagicMock()
    mock_result.scalar.return_value = 1  # cycle detected
    db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc:
        await task_manager.add_dependency(db, task, depends_on_id)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_remove_dependency_found():
    db = AsyncMock()
    task = _make_task()
    dep_mock = MagicMock()
    _mock_execute_scalars(db, first=dep_mock)
    db.delete = AsyncMock()

    await task_manager.remove_dependency(db, task, uuid.uuid4())
    db.delete.assert_called_once_with(dep_mock)


@pytest.mark.asyncio
async def test_remove_dependency_not_found():
    db = AsyncMock()
    task = _make_task()
    _mock_execute_scalars(db, first=None)
    db.delete = AsyncMock()

    await task_manager.remove_dependency(db, task, uuid.uuid4())
    db.delete.assert_not_called()


# ─── assign_task ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assign_task_member_exists():
    db = AsyncMock()
    task = _make_task()
    member = MagicMock()
    _mock_execute_scalars(db, first=member)
    assignee_id = uuid.uuid4()

    await task_manager.assign_task(db, task, assignee_id)
    assert task.assignee_id == assignee_id


@pytest.mark.asyncio
async def test_assign_task_not_member():
    from fastapi import HTTPException

    db = AsyncMock()
    task = _make_task()
    _mock_execute_scalars(db, first=None)

    with pytest.raises(HTTPException) as exc:
        await task_manager.assign_task(db, task, uuid.uuid4())
    assert exc.value.status_code == 400


# ─── add_comment / get_comments ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_comment():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    task_id = uuid.uuid4()
    user_id = uuid.uuid4()

    comment = await task_manager.add_comment(db, task_id, user_id, "Hello")
    db.add.assert_called_once()
    db.flush.assert_called_once()
    assert comment.task_id == task_id
    assert comment.user_id == user_id
    assert comment.content == "Hello"


@pytest.mark.asyncio
async def test_get_comments():
    db = AsyncMock()
    mock_comments = [MagicMock(), MagicMock()]
    _mock_execute_scalars(db, all_items=mock_comments)

    result = await task_manager.get_comments(db, uuid.uuid4())
    assert len(result) == 2


# ─── check_and_unblock_dependents ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_and_unblock_no_dependents():
    db = AsyncMock()

    call_count = 0

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        return mock_result

    db.execute = AsyncMock(side_effect=side_effect)

    result = await task_manager.check_and_unblock_dependents(db, uuid.uuid4())
    assert result == []


# ─── cascade_deadlines ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cascade_deadlines_no_descendants():
    db = AsyncMock()

    call_count = 0

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        mock_result.all.return_value = []  # no descendant IDs from CTE
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        return mock_result

    db.execute = AsyncMock(side_effect=side_effect)

    count = await task_manager.cascade_deadlines(db, uuid.uuid4(), delta_days=3)
    assert count == 0


@pytest.fixture(autouse=True)
def _skip_project_scope_checks(monkeypatch):
    """These mocked tests predate the project-scope checks (see test_task_rules.py)."""
    from unittest.mock import AsyncMock as _AsyncMock

    from app.modules.tasks.manager import task_manager as _tm

    async def _live_task(db, task_id, project_id, error, status_code=400):
        from fastapi import HTTPException as _HTTPException

        found = await db.get(None, task_id)
        if not found:
            raise _HTTPException(status_code=status_code, detail=error)
        return found

    monkeypatch.setattr(_tm, "_check_refs", _AsyncMock())
    monkeypatch.setattr(_tm, "_dependency_exists", _AsyncMock(return_value=False))
    monkeypatch.setattr(_tm, "_get_live_task", _live_task)
