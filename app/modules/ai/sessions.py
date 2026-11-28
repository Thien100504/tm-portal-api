"""
Chat sessions for the assistant sidebar.

A session belongs to one user and one scope: a project (project_id set) or a
whole workspace (project_id empty). Every call re-checks that the user can
still reach that scope and that the workspace has AI enabled.
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import AIChatMessage, AIChatSession
from app.models.user import User
from app.models.workspace import Workspace
from app.modules.projects.manager import project_manager

TITLE_MAX = 255


async def check_scope(
    db: AsyncSession,
    user: User,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID | None,
) -> Workspace:
    """The user may chat in this workspace (or project of it), and AI is on there."""
    workspace = await db.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="workspace.not_found")
    if project_id:
        project = await project_manager.get_project_for_user(db, project_id, user.id)
        if not project or project.workspace_id != workspace_id:
            raise HTTPException(status_code=403, detail="project.permission_denied")
    elif not await project_manager.is_workspace_member(db, workspace_id, user.id):
        raise HTTPException(status_code=403, detail="workspace.access_denied")
    if not (workspace.settings or {}).get("enable_ai", True):
        raise HTTPException(status_code=403, detail="feature_disabled:enable_ai")
    return workspace


async def get_session(
    db: AsyncSession, session_id: uuid.UUID, user: User
) -> AIChatSession:
    """The user's own session, still within a scope they can reach."""
    session = await db.get(AIChatSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="chatbot.error_session_not_found")
    workspace_id = session.workspace_id
    if workspace_id is None and session.project_id:
        # sessions created before workspace_id was recorded
        project = await project_manager.get_project_for_user(
            db, session.project_id, user.id
        )
        if not project:
            raise HTTPException(status_code=403, detail="project.permission_denied")
        workspace_id = project.workspace_id
    if workspace_id is None:
        raise HTTPException(status_code=404, detail="chatbot.error_session_not_found")
    await check_scope(db, user, workspace_id, session.project_id)
    return session


async def list_sessions(
    db: AsyncSession,
    user: User,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID | None,
) -> list[AIChatSession]:
    """Newest first: the project's sessions, or the workspace-wide ones."""
    await check_scope(db, user, workspace_id, project_id)
    query = select(AIChatSession).where(AIChatSession.user_id == user.id)
    if project_id:
        query = query.where(AIChatSession.project_id == project_id)
    else:
        query = query.where(
            AIChatSession.workspace_id == workspace_id,
            AIChatSession.project_id.is_(None),
        )
    query = query.order_by(AIChatSession.updated_at.desc())
    return list((await db.execute(query)).scalars().all())


async def create_session(
    db: AsyncSession,
    user: User,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID | None,
    title: str | None,
) -> AIChatSession:
    await check_scope(db, user, workspace_id, project_id)
    session = AIChatSession(
        user_id=user.id,
        workspace_id=workspace_id,
        project_id=project_id,
        title=(title or "").strip()[:TITLE_MAX] or None,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def rename_session(
    db: AsyncSession, session_id: uuid.UUID, user: User, title: str
) -> AIChatSession:
    session = await get_session(db, session_id, user)
    session.title = title.strip()[:TITLE_MAX] or None
    await db.commit()
    await db.refresh(session)
    return session


async def delete_session(db: AsyncSession, session_id: uuid.UUID, user: User) -> None:
    session = await get_session(db, session_id, user)
    await db.execute(
        delete(AIChatMessage).where(AIChatMessage.session_id == session.id)
    )
    await db.delete(session)
    await db.commit()


async def session_messages(
    db: AsyncSession, session_id: uuid.UUID, user: User
) -> list[AIChatMessage]:
    session = await get_session(db, session_id, user)
    query = (
        select(AIChatMessage)
        .where(AIChatMessage.session_id == session.id)
        .order_by(AIChatMessage.created_at.asc())
    )
    return list((await db.execute(query)).scalars().all())
