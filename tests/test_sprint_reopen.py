import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.modules.sprints.manager import sprint_manager


def _result(first):
    res = MagicMock()
    res.scalars.return_value.first.return_value = first
    return res


def _db(*firsts):
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[_result(f) for f in firsts])
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _sprint(status="completed", started_at=datetime(2026, 11, 1, tzinfo=UTC)):
    return MagicMock(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        status=status,
        started_at=started_at,
        completed_at=datetime(2026, 11, 14, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_cannot_reopen_when_a_later_sprint_has_started():
    # sprint 2 started (and maybe completed) after sprint 1
    db = _db(None, uuid.uuid4())
    sprint1 = _sprint()
    with pytest.raises(HTTPException) as exc:
        await sprint_manager.reopen_sprint(db, sprint1)
    assert exc.value.detail == "sprint.error_newer_sprint_started"
    assert sprint1.status == "completed"
    newer_query = str(db.execute.await_args_list[1].args[0])
    assert "started_at >" in newer_query
    assert "sprints.status IN" in newer_query


@pytest.mark.asyncio
async def test_can_reopen_the_latest_started_sprint():
    # a later sprint that is still in planning does not block
    db = _db(None, None)
    sprint = _sprint()
    result = await sprint_manager.reopen_sprint(db, sprint)
    assert result.status == "active"
    assert result.completed_at is None
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_cannot_reopen_while_another_sprint_is_active():
    db = _db(_sprint(status="active"))
    with pytest.raises(HTTPException) as exc:
        await sprint_manager.reopen_sprint(db, _sprint())
    assert exc.value.detail == "sprint.error_already_active"


@pytest.mark.asyncio
async def test_cannot_reopen_a_sprint_that_is_not_completed():
    with pytest.raises(HTTPException) as exc:
        await sprint_manager.reopen_sprint(_db(), _sprint(status="planning"))
    assert exc.value.detail == "sprint.error_not_completed"


@pytest.mark.asyncio
async def test_sprint_without_started_at_is_blocked_by_any_started_sprint():
    db = _db(None, uuid.uuid4())
    with pytest.raises(HTTPException):
        await sprint_manager.reopen_sprint(db, _sprint(started_at=None))
    assert "started_at >" not in str(db.execute.await_args_list[1].args[0])
