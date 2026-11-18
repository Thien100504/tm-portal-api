"""
Project Event Pipeline — side-effects for project membership changes.
"""

import logging
from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.pipeline import EventContext, EventHandler, Parallel, Pipeline
from app.models.user import User
from app.modules.notifications import service as notif_svc
from app.modules.websocket.manager import manager

logger = logging.getLogger(__name__)


class AuditLogHandler(EventHandler):
    name = "audit_log"

    async def handle(self, ctx: EventContext) -> None:
        logger.info(
            "AUDIT | event=%s project=%s actor=%s target=%s",
            ctx.event_type,
            str(ctx.task.id)[:8],
            ctx.actor.full_name,
            ctx.extra.get("target_user_name", "?"),
        )


class WebSocketHandler(EventHandler):
    name = "websocket"

    async def handle(self, ctx: EventContext) -> None:
        await manager.broadcast_to_project(
            ctx.task.id,
            {
                "action": "invalidate",
                "entity": "members",
                "actor_id": str(ctx.actor.id),
            },
        )


class NotificationHandler(EventHandler):
    name = "notification"

    async def should_run(self, ctx: EventContext) -> bool:
        target = ctx.extra.get("target_user_id")
        return target is not None and target != ctx.actor.id

    async def handle(self, ctx: EventContext) -> None:
        target_user_id = ctx.extra["target_user_id"]

        templates = {
            "project.member_added": {
                "title_key": "notification.project.member_added",
                "title_params": {"name": ctx.task.name[:60]},
                "message_key": "notification.project.added_by",
                "message_params": {"actor": ctx.actor.full_name},
                "type": "info",
            },
            "project.member_removed": {
                "title_key": "notification.project.member_removed",
                "title_params": {"name": ctx.task.name[:60]},
                "message_key": "notification.project.removed_by",
                "message_params": {"actor": ctx.actor.full_name},
                "type": "warning",
            },
        }

        meta = templates.get(ctx.event_type)
        if not meta:
            return

        await notif_svc.create_and_push(
            ctx.db,
            user_id=target_user_id,
            event_type=ctx.event_type,  # distinct dedup keys for added/removed
            title_key=meta["title_key"],
            title_params=meta["title_params"],
            message_key=meta["message_key"],
            message_params=meta["message_params"],
            type=meta["type"],
            entity_type="project",
            entity_id=ctx.task.id,
            project_id=ctx.task.id,
        )


_pipeline = Pipeline(
    "project_events",
    [
        Parallel(AuditLogHandler(), WebSocketHandler()),
        NotificationHandler(),
    ],
)


class ProjectEventService:
    async def emit(
        self,
        db: AsyncSession,
        background_tasks: BackgroundTasks,
        event_type: str,
        project,
        actor: User,
        extra: Optional[dict] = None,
    ):
        ctx = EventContext(
            db=db,
            background_tasks=background_tasks,
            event_type=event_type,
            task=project,
            actor=actor,
            extra=extra or {},
        )
        await _pipeline.run(ctx)


project_events = ProjectEventService()
