"""Sprint rules: status only via the lifecycle, date validation, target sprint checks."""

import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.sprints.manager import sprint_manager
from app.modules.sprints.schemas import SprintCreate, SprintUpdate, check_sprint_dates


def test_status_is_not_accepted_on_create_or_update():
    assert "status" not in SprintCreate(name="S1", status="completed").model_dump()
    assert "status" not in SprintUpdate(status="active").model_dump(exclude_unset=True)


def test_dates_are_validated():
    with pytest.raises(ValidationError):
        SprintCreate(name="S1", start_date=date(2026, 5, 10), end_date=date(2026, 5, 1))
    with pytest.raises(ValidationError):
        SprintCreate(name="S1", start_date=date(1, 1, 1), end_date=date(9999, 12, 31))
    assert check_sprint_dates(date(2026, 5, 1), date(2026, 5, 14)) is None
    assert (
        check_sprint_dates(date(2026, 5, 14), date(2026, 5, 1))
        == "sprint.error_end_before_start"
    )
    assert check_sprint_dates(None, date(2026, 5, 1)) is None


def test_name_cannot_be_null():
    with pytest.raises(ValidationError):
        SprintUpdate(name=None)
    assert SprintUpdate(goal="g").model_dump(exclude_unset=True) == {"goal": "g"}


def _db_with(target, tasks=()):
    db = MagicMock()
    db.get = AsyncMock(return_value=target)
    db.flush = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(tasks)
    db.execute = AsyncMock(return_value=result)
    return db


def _sprint(project_id=None, status="active"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=project_id or uuid.uuid4(),
        status=status,
        is_deleted=False,
    )


def _task(status, sprint_id, hours=None, updated_at=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=status,
        sprint_id=sprint_id,
        estimated_hours=hours,
        updated_at=updated_at,
    )


@pytest.mark.asyncio
async def test_cannot_move_tasks_into_another_projects_sprint():
    sprint = _sprint()
    foreign = _sprint(status="planning")  # another project
    task = _task("todo", sprint.id)
    with pytest.raises(HTTPException) as exc:
        await sprint_manager.complete_sprint(
            _db_with(foreign, [task]), sprint, "next_sprint", foreign.id
        )
    assert exc.value.detail == "sprint.error_invalid_target_sprint"
    assert task.sprint_id == sprint.id


@pytest.mark.asyncio
async def test_cannot_target_the_sprint_itself():
    sprint = _sprint()
    with pytest.raises(HTTPException):
        await sprint_manager.complete_sprint(
            _db_with(sprint, []), sprint, "next_sprint", sprint.id
        )


@pytest.mark.asyncio
async def test_unfinished_tasks_move_to_a_sprint_of_the_same_project():
    sprint = _sprint()
    nxt = _sprint(project_id=sprint.project_id, status="planning")
    done = _task(
        "done", sprint.id, hours=3, updated_at=datetime(2026, 11, 5, tzinfo=UTC)
    )
    todo = _task("todo", sprint.id)
    summary = await sprint_manager.complete_sprint(
        _db_with(nxt, [done, todo]), sprint, "next_sprint", nxt.id
    )
    assert todo.sprint_id == nxt.id and done.sprint_id == sprint.id
    assert summary == {"done_count": 1, "incomplete_count": 1, "total_count": 2}
    assert sprint.status == "completed"
    # the report keeps the moved task even though it left the sprint
    assert sprint.completion_snapshot == {
        "tasks": [
            {
                "id": str(done.id),
                "hours": 3,
                "done": True,
                "done_at": "2026-11-05T00:00:00+00:00",
            },
            {"id": str(todo.id), "hours": 1.0, "done": False, "done_at": None},
        ]
    }
