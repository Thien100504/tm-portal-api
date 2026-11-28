import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.sprints.manager import sprint_manager

START = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
END = datetime(2026, 11, 5, 15, 0, tzinfo=UTC)


def _completed(snapshot):
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        status="completed",
        started_at=START,
        completed_at=END,
        start_date=None,
        end_date=None,
        completion_snapshot=snapshot,
    )


SNAPSHOT = {
    "tasks": [
        # done on day 1
        {"id": "a", "hours": 2, "done": True, "done_at": "2026-11-03T10:00:00+00:00"},
        # done on the last, partial day (after 09:00, before completion at 15:00)
        {"id": "b", "hours": 1, "done": True, "done_at": "2026-11-05T12:00:00+00:00"},
        # unfinished, moved to the backlog when the sprint was completed
        {"id": "c", "hours": 3, "done": False, "done_at": None},
    ]
}


def _db_without_queries():
    db = MagicMock()
    db.execute = AsyncMock(side_effect=AssertionError("snapshot must be used"))
    return db


@pytest.mark.asyncio
async def test_completed_sprint_stats_come_from_the_snapshot():
    stats = await sprint_manager.get_stats(_db_without_queries(), _completed(SNAPSHOT))
    assert stats["total_tasks"] == 3
    assert stats["done_tasks"] == 2
    assert stats["incomplete_tasks"] == 1
    assert stats["completion_rate"] == 66.7


@pytest.mark.asyncio
async def test_completed_sprint_burndown_keeps_unfinished_work():
    points = await sprint_manager.get_burndown(
        _db_without_queries(), _completed(SNAPSHOT)
    )
    assert points[0]["remaining_hours"] == 6
    assert points[0]["ideal_hours"] == 6
    # unfinished work stays on the chart: it never reaches 0
    assert points[-1]["remaining_hours"] == 3
    # the last point is the completion itself, so task "b" has burned down
    assert points[-1]["date"] == "05/11"
    assert points[-2]["remaining_hours"] == 4


@pytest.mark.asyncio
async def test_completed_sprint_without_snapshot_uses_current_tasks():
    task = SimpleNamespace(
        estimated_hours=None,
        status="done",
        updated_at=datetime(2026, 11, 3, tzinfo=UTC),
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [task]
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    stats = await sprint_manager.get_stats(db, _completed(None))
    assert stats["total_tasks"] == 1
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_active_sprint_ignores_a_stale_snapshot():
    sprint = _completed(SNAPSHOT)
    sprint.status = "active"
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    assert (await sprint_manager.get_stats(db, sprint))["total_tasks"] == 0


@pytest.mark.asyncio
async def test_reopen_clears_the_snapshot():
    empty = MagicMock()
    empty.scalars.return_value.first.return_value = None
    db = MagicMock()
    db.execute = AsyncMock(return_value=empty)
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    sprint = _completed(SNAPSHOT)
    await sprint_manager.reopen_sprint(db, sprint)
    assert sprint.status == "active"
    assert sprint.completion_snapshot is None
