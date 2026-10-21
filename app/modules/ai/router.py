"""
AI Router

- GET  /projects/{id}/ai-insights     — Project health & AI narrative
- GET  /projects/{id}/ai-metrics      — AI evaluation metrics dashboard
- PATCH /ai-metrics/{id}/feedback     — User feedback on AI suggestion
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.modules.auth.dependencies import get_current_active_user
from app.modules.projects.dependencies import get_project_access
from app.modules.ai.schemas import (
    AIInsightsResponse,
    AIMetricsResponse,
    AIMetricFeedback,
)
from app.modules.ai import service as ai_service

router = APIRouter(prefix="/projects/{project_id}", tags=["ai"])


@router.get("/ai-insights", response_model=AIInsightsResponse)
async def get_ai_insights(
    project_id: uuid.UUID,
    lang: str = Query(default="vi", pattern="^(vi|en)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    await get_project_access(project_id, db, current_user)
    return await ai_service.get_ai_insights(db, project_id, lang=lang)


@router.get("/ai-metrics", response_model=AIMetricsResponse)
async def get_ai_metrics(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    await get_project_access(project_id, db, current_user)
    return await ai_service.get_ai_metrics(db, project_id)


@router.patch("/ai-metrics/{metric_id}")
async def submit_feedback(
    project_id: uuid.UUID,
    metric_id: uuid.UUID,
    body: AIMetricFeedback,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    await get_project_access(project_id, db, current_user)
    return await ai_service.update_metric_feedback(db, metric_id, body)
