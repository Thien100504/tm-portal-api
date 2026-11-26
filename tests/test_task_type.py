import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.tasks.manager import task_manager
from app.modules.tasks.schemas import TaskCreate, TaskResponseBase, TaskUpdate


def test_task_type_defaults_to_task():
    task = TaskCreate(title="t", project_id=uuid.uuid4())
    assert task.type == "task"


@pytest.mark.parametrize("value", ["story", "task", "bug"])
def test_task_type_accepts_known_types(value):
    assert TaskCreate(title="t", project_id=uuid.uuid4(), type=value).type == value


def test_task_type_rejects_unknown_types():
    with pytest.raises(ValidationError):
        TaskCreate(title="t", project_id=uuid.uuid4(), type="epic")
    with pytest.raises(ValidationError):
        TaskUpdate(type="feature")


def test_task_response_exposes_type():
    assert "type" in TaskResponseBase.model_fields


@pytest.mark.asyncio
async def test_story_cannot_be_created_as_a_subtask():
    db = AsyncMock()
    obj_in = TaskCreate(
        title="s", project_id=uuid.uuid4(), type="story", parent_task_id=uuid.uuid4()
    )
    with pytest.raises(HTTPException) as exc:
        await task_manager.create_task(db, obj_in, uuid.uuid4())
    assert exc.value.status_code == 400
    assert exc.value.detail == "task.story_cannot_be_subtask"
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("obj_in", [TaskUpdate(type="story"), {"type": "story"}])
async def test_subtask_cannot_become_a_story(obj_in):
    db = AsyncMock()
    subtask = MagicMock(parent_task_id=uuid.uuid4(), deadline=None)
    with pytest.raises(HTTPException) as exc:
        await task_manager.update(db, db_obj=subtask, obj_in=obj_in)
    assert exc.value.detail == "task.story_cannot_be_subtask"
    db.get.assert_not_awaited()
