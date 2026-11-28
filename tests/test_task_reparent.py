"""Moving an existing task under a story/task (or out of it) via PUT /tasks/{id}."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.modules.tasks import schemas
from app.modules.tasks.manager import task_manager

PROJECT = uuid.uuid4()


def _task(**kw):
    data = {
        "id": uuid.uuid4(),
        "project_id": PROJECT,
        "workspace_id": uuid.uuid4(),
        "is_deleted": False,
        "parent_task_id": None,
        "type": "task",
        "deadline": None,
        "sprint_id": None,
        "epic_id": None,
    }
    data.update(kw)
    return SimpleNamespace(**data)


def _db(parent=None, has_children=False):
    db = MagicMock()
    db.get = AsyncMock(return_value=parent)
    db.scalar = AsyncMock(return_value=uuid.uuid4() if has_children else None)
    return db


async def _move(task, parent_id, db, **extra):
    return await task_manager._apply_parent_change(
        db, task, {"parent_task_id": parent_id, **extra}, extra.get("deadline")
    )


def test_update_schema_accepts_parent_task_id():
    pid = uuid.uuid4()
    assert schemas.TaskUpdate(parent_task_id=pid).model_dump(exclude_unset=True) == {
        "parent_task_id": pid
    }
    assert schemas.TaskUpdate(parent_task_id=None).model_dump(exclude_unset=True) == {
        "parent_task_id": None
    }


@pytest.mark.asyncio
async def test_attached_task_follows_parent_sprint_and_epic():
    parent = _task(type="story", sprint_id=uuid.uuid4(), epic_id=uuid.uuid4())
    out = await _move(_task(), parent.id, _db(parent))
    assert out["sprint_id"] == parent.sprint_id
    assert out["epic_id"] == parent.epic_id


@pytest.mark.asyncio
async def test_explicit_sprint_in_same_update_wins():
    parent = _task(type="story", sprint_id=uuid.uuid4())
    other = uuid.uuid4()
    out = await _move(_task(), parent.id, _db(parent), sprint_id=other)
    assert out["sprint_id"] == other


@pytest.mark.asyncio
async def test_detaching_keeps_everything_else():
    task = _task(parent_task_id=uuid.uuid4())
    db = _db()
    assert await _move(task, None, db) == {"parent_task_id": None}
    db.get.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case, code",
    [
        ("self", "task.cannot_parent_itself"),
        ("missing", "task.parent_not_found"),
        ("other_project", "task.parent_not_found"),
        ("deleted", "task.parent_not_found"),
        ("parent_is_subtask", "task.subtask_depth_limit"),
        ("story_child", "task.story_cannot_be_subtask"),
        ("has_children", "task.has_subtasks"),
        ("late_deadline", "task.error_subtask_deadline_later_than_parent"),
    ],
)
async def test_invalid_moves_are_rejected(case, code):
    task = _task()
    parent = _task(type="story")
    parent_id = parent.id
    extra = {}
    db_kw = {"parent": parent}
    if case == "self":
        parent_id = task.id
    elif case == "missing":
        db_kw["parent"] = None
    elif case == "other_project":
        parent.project_id = uuid.uuid4()
    elif case == "deleted":
        parent.is_deleted = True
    elif case == "parent_is_subtask":
        parent.parent_task_id = uuid.uuid4()
    elif case == "story_child":
        task.type = "story"
    elif case == "has_children":
        db_kw["has_children"] = True
    elif case == "late_deadline":
        parent.deadline = datetime(2026, 1, 1, tzinfo=UTC)
        extra["deadline"] = datetime(2026, 2, 1, tzinfo=UTC)
    with pytest.raises(HTTPException) as exc:
        await _move(task, parent_id, _db(**db_kw), **extra)
    assert exc.value.detail == code


@pytest.mark.asyncio
async def test_update_skips_old_parent_deadline_rule_when_detaching(monkeypatch):
    """Detaching a subtask with a deadline later than its old parent is fine."""
    old_parent = _task(deadline=datetime(2026, 1, 1, tzinfo=UTC))
    task = _task(parent_task_id=old_parent.id)
    db = _db(old_parent)
    empty = MagicMock()
    empty.scalars.return_value = MagicMock(__iter__=lambda _: iter(()), all=lambda: [])
    db.execute = AsyncMock(return_value=empty)
    base_update = AsyncMock(return_value=task)
    monkeypatch.setattr(
        type(task_manager).__mro__[1], "update", base_update, raising=True
    )
    monkeypatch.setattr(task_manager, "_check_refs", AsyncMock())
    await task_manager.update(
        db,
        db_obj=task,
        obj_in=schemas.TaskUpdate(
            parent_task_id=None, deadline=datetime(2026, 3, 1, tzinfo=UTC)
        ),
    )
    assert base_update.await_args.kwargs["obj_in"]["parent_task_id"] is None


@pytest.mark.asyncio
async def test_story_cannot_be_moved_under_a_parent_via_type_change():
    task = _task()
    with pytest.raises(HTTPException) as exc:
        await task_manager.update(
            _db(),
            db_obj=task,
            obj_in={"type": "story", "parent_task_id": uuid.uuid4()},
        )
    assert exc.value.detail == "task.story_cannot_be_subtask"


@pytest.mark.asyncio
async def test_new_subtask_inherits_parent_epic_and_sprint(monkeypatch):
    parent = _task(type="story", epic_id=uuid.uuid4(), sprint_id=uuid.uuid4())
    db = _db(parent)
    seen = {}

    async def stop(_db, project_id, workspace_id, **refs):
        seen.update(refs)
        raise RuntimeError("stop")

    db.execute = AsyncMock(return_value=MagicMock(scalar=lambda: 0))
    monkeypatch.setattr(task_manager, "_check_refs", stop)
    with pytest.raises(RuntimeError):
        await task_manager.create_task(
            db,
            obj_in=schemas.TaskCreate(
                title="t", project_id=PROJECT, parent_task_id=parent.id
            ),
            creator_id=uuid.uuid4(),
        )
    assert seen["epic_id"] == parent.epic_id
    assert seen["sprint_id"] == parent.sprint_id
