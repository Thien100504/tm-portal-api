"""
Sprint Event Pipeline — side-effects for sprint lifecycle actions.

Handlers:
  1. MetadataHandler      — build notification content
  2. AuditLog + WebSocket — parallel
  3. Notification          — in-app notifications
  4. RabbitMQHandler       — Telegram General channel (with retry)
"""

import logging
from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.pipeline import (
    EventContext,
    EventHandler,
    Parallel,
    Pipeline,
    RetryPolicy,
)
from app.events.publisher import EventPublisher
from app.models.project import Project, ProjectMember
from app.models.user import User
from app.modules.notifications import service as notif_svc
from app.modules.websocket.manager import manager

logger = logging.getLogger(__name__)


def _publish_sync(routing_key: str, payload: dict):
    try:
        with EventPublisher() as pub:
            pub.publish(routing_key, payload)
    except Exception:
        logger.exception("RabbitMQ publish failed: %s", routing_key)


class MetadataHandler(EventHandler):
    name = "metadata"

    TEMPLATES = {
        "sprint.started": lambda s, a: {
            "title_key": "notification.sprint.started",
            "title_params": {"name": s.name[:60]},
            "message_key": "notification.sprint.started_by",
            "message_params": {"actor": a.full_name},
            "type": "info",
        },
        "sprint.completed": lambda s, a: {
            "title_key": "notification.sprint.completed",
            "title_params": {"name": s.name[:60]},
            "message_key": "notification.sprint.completed_by",
            "message_params": {"actor": a.full_name},
            "type": "success",
        },
        "sprint.reopened": lambda s, a: {
            "title_key": "notification.sprint.reopened",
            "title_params": {"name": s.name[:60]},
            "message_key": "notification.sprint.reopened_by",
            "message_params": {"actor": a.full_name},
            "type": "warning",
        },
        "sprint.created": lambda s, a: {
            "title_key": "notification.sprint.created",
            "title_params": {"name": s.name[:60]},
            "message_key": "notification.sprint.created_by",
            "message_params": {"actor": a.full_name},
            "type": "info",
        },
    }

    async def handle(self, ctx: EventContext) -> None:
        template_fn = self.TEMPLATES.get(ctx.event_type)
        if template_fn:
            ctx.meta = {**template_fn(ctx.task, ctx.actor), "entity_type": "sprint"}
        else:
            ctx.meta = {
                "title_key": "notification.sprint.generic",
                "title_params": {"name": ctx.task.name},
                "type": "info",
                "entity_type": "sprint",
            }
        ctx.meta.update(ctx.extra)


class AuditLogHandler(EventHandler):
    name = "audit_log"

    async def handle(self, ctx: EventContext) -> None:
        logger.info(
            "AUDIT | event=%s sprint=%s project=%s actor=%s",
            ctx.event_type,
            ctx.task.name,
            str(ctx.task.project_id)[:8],
            ctx.actor.full_name,
        )


class WebSocketHandler(EventHandler):
    name = "websocket"

    async def handle(self, ctx: EventContext) -> None:
        await manager.broadcast_to_project(
            ctx.task.project_id,
            {
                "action": "invalidate",
                "entity": "sprints",
                "actor_id": str(ctx.actor.id),
            },
        )
        if ctx.event_type in ("sprint.completed", "sprint.reopened"):
            await manager.broadcast_to_project(
                ctx.task.project_id,
                {
                    "action": "invalidate",
                    "entity": "tasks",
                    "actor_id": str(ctx.actor.id),
                },
            )


class NotificationHandler(EventHandler):
    name = "notification"

    async def should_run(self, ctx: EventContext) -> bool:
        return ctx.event_type != "sprint.created"

    async def handle(self, ctx: EventContext) -> None:
        project_id = ctx.task.project_id
        result = await ctx.db.execute(
            select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)
        )
        member_ids = {row[0] for row in result.all()}
        member_ids.discard(ctx.actor.id)

        for user_id in member_ids:
            await notif_svc.create_and_push(
                ctx.db,
                user_id=user_id,
                title_key=ctx.meta.get("title_key"),
                title_params=ctx.meta.get("title_params"),
                message_key=ctx.meta.get("message_key"),
                message_params=ctx.meta.get("message_params"),
                type=ctx.meta["type"],
                entity_type="sprint",
                entity_id=ctx.task.id,
                project_id=project_id,
            )


class RabbitMQHandler(EventHandler):
    name = "rabbitmq"

    async def should_run(self, ctx: EventContext) -> bool:
        return ctx.event_type != "sprint.created"

    async def handle(self, ctx: EventContext) -> None:
        project = await ctx.db.get(Project, ctx.task.project_id)
        if not project or not project.telegram_chat_id:
            return

        payload = {
            **ctx.meta,
            "event": ctx.event_type,
            "project_id": str(ctx.task.project_id),
            "telegram_chat_id": project.telegram_chat_id,
            "channels": ["telegram"],
        }
        ctx.background_tasks.add_task(_publish_sync, ctx.event_type, payload)


_pipeline = Pipeline(
    "sprint_events",
    [
        MetadataHandler(),
        Parallel(AuditLogHandler(), WebSocketHandler()),
        NotificationHandler(),
        RabbitMQHandler(retry=RetryPolicy(max_retries=1, backoff_base=0.3)),
    ],
)


class SprintEventService:
    async def emit(
        self,
        db: AsyncSession,
        background_tasks: BackgroundTasks,
        event_type: str,
        sprint,
        actor: User,
        extra: Optional[dict] = None,
    ):
        ctx = EventContext(
            db=db,
            background_tasks=background_tasks,
            event_type=event_type,
            task=sprint,
            actor=actor,
            extra=extra or {},
        )
        await _pipeline.run(ctx)


sprint_events = SprintEventService()
