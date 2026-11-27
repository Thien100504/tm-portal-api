"""
AI Router

- GET  /projects/{id}/ai-insights     — Project health & AI narrative
- GET  /projects/{id}/ai-metrics      — AI evaluation metrics dashboard
- PATCH /ai-metrics/{id}/feedback     — User feedback on AI suggestion
"""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.modules.ai import service as ai_service
from app.modules.ai.schemas import (
    AIInsightsResponse,
    AIMetricFeedback,
    AIMetricsResponse,
    ChatMessageInput,
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSessionResponse,
)
from app.modules.auth.dependencies import get_current_active_user
from app.modules.projects.dependencies import (
    get_project_access,
    require_project_permission,
)
from app.modules.workspaces.features import require_feature

router = APIRouter(
    prefix="/projects/{project_id}",
    tags=["ai"],
    dependencies=[Depends(require_feature("enable_ai"))],
)


@router.get("/ai-insights", response_model=AIInsightsResponse)
async def get_ai_insights(
    project_id: uuid.UUID,
    lang: str = Query("vi", description="Language: 'vi' or 'en'"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    await get_project_access(project_id, db, current_user)
    return await ai_service.get_ai_insights(db, project_id, lang)


@router.get("/ai-metrics", response_model=AIMetricsResponse)
async def get_ai_metrics(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    await get_project_access(project_id, db, current_user)
    return await ai_service.get_ai_metrics(db, project_id)


@router.get("/chat/sessions", response_model=list[ChatSessionResponse])
async def list_sessions(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    await get_project_access(project_id, db, current_user)
    return await ai_service.get_chat_sessions(db, project_id, current_user.id)


@router.post("/chat/sessions", response_model=ChatSessionResponse)
async def create_session(
    project_id: uuid.UUID,
    body: ChatSessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    await get_project_access(project_id, db, current_user)
    return await ai_service.create_chat_session(
        db, project_id, current_user.id, body.title or "New Conversation"
    )


@router.get(
    "/chat/sessions/{session_id}/messages", response_model=list[ChatMessageResponse]
)
async def get_messages(
    project_id: uuid.UUID,
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    await get_project_access(project_id, db, current_user)
    return await ai_service.get_chat_messages(
        db, session_id, current_user.id, project_id
    )


@router.post("/chat/sessions/{session_id}/stream")
async def chat_stream(
    project_id: uuid.UUID,
    session_id: uuid.UUID,
    body: ChatMessageInput,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    await get_project_access(project_id, db, current_user)
    await ai_service.check_chat_ready(db, project_id, session_id, current_user.id)

    async def event_stream():
        async for chunk in ai_service.chat_with_project(
            db,
            project_id,
            session_id,
            body.content,
            current_user,
            lang=body.lang,
        ):
            yield chunk

    return StreamingResponse(event_stream(), media_type="text/plain; charset=utf-8")


@router.patch("/ai-metrics/{metric_id}")
async def submit_feedback(
    project_id: uuid.UUID,
    metric_id: uuid.UUID,
    body: AIMetricFeedback,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    # rejecting a breakdown deletes subtasks: it needs the right to edit tasks
    await require_project_permission("task.update")(project_id, db, current_user)
    return await ai_service.update_metric_feedback(
        db, project_id, metric_id, body, user_id=current_user.id
    )
