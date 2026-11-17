"""AI feedback scope and validation."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.ai import service as ai_service
from app.modules.ai.schemas import AIMetricFeedback


def test_feedback_is_validated():
    with pytest.raises(ValidationError):
        AIMetricFeedback(status="whatever")
    with pytest.raises(ValidationError):
        AIMetricFeedback(status="applied", feedback_note="x" * 501)
    assert AIMetricFeedback(status="rejected").status == "rejected"


@pytest.mark.asyncio
async def test_feedback_on_a_metric_of_another_project_is_not_found():
    metric = SimpleNamespace(project_id=uuid.uuid4())
    db = MagicMock()
    db.get = AsyncMock(return_value=metric)
    with pytest.raises(HTTPException) as exc:
        await ai_service.update_metric_feedback(
            db, uuid.uuid4(), uuid.uuid4(), AIMetricFeedback(status="rejected")
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_rejecting_a_breakdown_deletes_only_the_subtasks_it_created():
    project_id = uuid.uuid4()
    created = uuid.uuid4()
    metric = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=project_id,
        feature="breakdown",
        task_id=uuid.uuid4(),
        output_data={"created_ids": [str(created)]},
        status="generated",
        feedback_note=None,
        feedback_at=None,
    )
    statements = []

    async def execute(stmt):
        statements.append(stmt)
        result = MagicMock()
        result.fetchall.return_value = [(created,)]
        return result

    db = MagicMock()
    db.get = AsyncMock(return_value=metric)
    db.execute = execute
    db.commit = AsyncMock()
    user = uuid.uuid4()
    await ai_service.update_metric_feedback(
        db, project_id, metric.id, AIMetricFeedback(status="rejected"), user_id=user
    )
    params = statements[0].compile().params
    assert created in next(v for v in params.values() if isinstance(v, list))
    assert user in params.values()
    assert metric.status == "rejected"
