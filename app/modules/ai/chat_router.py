"""
Assistant sidebar: chat sessions for a workspace or one of its projects.

- GET    /chat/status                               is an AI provider configured
- GET    /chat/sessions?workspace_id=&project_id=   list (no project_id = workspace chats)
- POST   /chat/sessions                             create
- PATCH  /chat/sessions/{id}                        rename
- DELETE /chat/sessions/{id}                        delete with its messages
- GET    /chat/sessions/{id}/messages
- POST   /chat/sessions/{id}/stream                 send a message, stream the reply
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.modules.ai import llm, sessions
from app.modules.ai import service as ai_service
from app.modules.ai.schemas import (
    ChatMessageInput,
    ChatMessageResponse,
    ChatSessionRename,
    ChatSessionResponse,
    ChatSessionScopeCreate,
    ChatStatusResponse,
)
from app.modules.ai.workspace_chat import chat_with_workspace
from app.modules.auth.dependencies import get_current_active_user

router = APIRouter(prefix="/chat", tags=["ai"])


@router.get("/status", response_model=ChatStatusResponse)
async def chat_status(current_user: User = Depends(get_current_active_user)):
    """Lets the UI show the assistant as unavailable before anyone types."""
    return ChatStatusResponse(configured=llm.is_configured())


@router.get("/sessions", response_model=list[ChatSessionResponse])
async def list_chat_sessions(
    workspace_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return await sessions.list_sessions(db, current_user, workspace_id, project_id)


@router.post(
    "/sessions",
    response_model=ChatSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_chat_session(
    body: ChatSessionScopeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return await sessions.create_session(
        db, current_user, body.workspace_id, body.project_id, body.title
    )


@router.patch("/sessions/{session_id}", response_model=ChatSessionResponse)
async def rename_chat_session(
    session_id: uuid.UUID,
    body: ChatSessionRename,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return await sessions.rename_session(db, session_id, current_user, body.title)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    await sessions.delete_session(db, session_id, current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageResponse])
async def list_chat_messages(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return await sessions.session_messages(db, session_id, current_user)


@router.post("/sessions/{session_id}/stream")
async def stream_chat_reply(
    session_id: uuid.UUID,
    body: ChatMessageInput,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    session = await sessions.get_session(db, session_id, current_user)
    if not llm.is_configured():
        raise HTTPException(status_code=503, detail="chatbot.error_not_configured")

    if session.project_id:
        reply = ai_service.chat_with_project(
            db,
            session.project_id,
            session.id,
            body.content,
            current_user,
            lang=body.lang,
        )
    else:
        reply = chat_with_workspace(
            db, session, body.content, current_user, lang=body.lang
        )
    return StreamingResponse(reply, media_type="text/plain; charset=utf-8")
