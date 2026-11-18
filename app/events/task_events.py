"""
Task Event Pipeline — orchestrates all side-effects for task actions.

Handlers:
  1. MetadataHandler    — build notification title/message (sequential, must run first)
  2. AuditLog + WebSocket — parallel (independent, no shared state)
  3. StakeholderHandler — resolve who to notify (sequential, feeds RabbitMQ)
  4. RabbitMQHandler    — publish to external consumers (retry on connection failure)
"""

import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import BackgroundTasks

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


# ═════════════════════════════════════════════════════════════════════
# Handler 1: Build notification metadata from templates
# ═════════════════════════════════════════════════════════════════════


class MetadataHandler(EventHandler):
    name = "metadata"

    TEMPLATES = {
        "task.created": lambda t, a: {
            "title_key": "notification.task.created",
            "title_params": {"title": t.title[:60]},
            "message_key": "notification.task.created_by",
            "message_params": {"actor": a.full_name},
            "type": "info",
        },
        "task.updated": lambda t, a: {
            "title_key": "notification.task.updated",
            "title_params": {"title": t.title[:60]},
            "message_key": "notification.task.updated_by",
            "message_params": {"actor": a.full_name},
            "type": "info",
        },
        "task.completed": lambda t, a: {
            "title_key": "notification.task.completed",
            "title_params": {"title": t.title[:60]},
            "message_key": "notification.task.completed_by",
            "message_params": {"actor": a.full_name},
            "type": "success",
        },
        "task.assigned": lambda t, a: {
            "title_key": "notification.task.assigned",
            "title_params": {"title": t.title[:60]},
            "message_key": "notification.task.assigned_by",
            "message_params": {"actor": a.full_name},
            "type": "assignment",
        },
        "task.commented": lambda t, a: {
            "title_key": "notification.task.commented",
            "title_params": {"actor": a.full_name},
            "message_key": "notification.task.commented_on",
            "message_params": {"title": t.title[:60]},
            "type": "info",
        },
        "task.unblocked": lambda t, a: {
            "title_key": "notification.task.unblocked",
            "title_params": {"title": t.title[:60]},
            "message_key": "notification.task.unblocked_message",
            "message_params": {},
            "type": "info",
        },
    }

    async def handle(self, ctx: EventContext) -> None:
        template_fn = self.TEMPLATES.get(ctx.event_type)
        if template_fn:
            ctx.meta = {**template_fn(ctx.task, ctx.actor), "entity_type": "task"}
        else:
            ctx.meta = {
                "title_key": "notification.task.generic",
                "title_params": {"title": ctx.task.title},
                "type": "info",
                "entity_type": "task",
            }
        ctx.meta.update(ctx.extra)


# ═════════════════════════════════════════════════════════════════════
# Handler 2: Structured audit log
# ═════════════════════════════════════════════════════════════════════


class AuditLogHandler(EventHandler):
    name = "audit_log"

    async def handle(self, ctx: EventContext) -> None:
        logger.info(
            "AUDIT | event=%s task_id=%s project_id=%s actor=%s(%s) meta_type=%s",
            ctx.event_type,
            str(ctx.task.id)[:8],
            str(ctx.task.project_id)[:8],
            ctx.actor.full_name,
            str(ctx.actor.id)[:8],
            ctx.meta.get("type", "?"),
        )


# ═════════════════════════════════════════════════════════════════════
# Handler 3: WebSocket broadcast
# ═════════════════════════════════════════════════════════════════════


class WebSocketHandler(EventHandler):
    name = "websocket"

    async def handle(self, ctx: EventContext) -> None:
        ws_entity = "comments" if ctx.event_type == "task.commented" else "tasks"
        ws_payload = {
            "action": "invalidate",
            "entity": ws_entity,
            "actor_id": str(ctx.actor.id),
        }
        if ctx.event_type == "task.commented":
            ws_payload["task_id"] = str(ctx.task.id)

        await manager.broadcast_to_project(ctx.task.project_id, ws_payload)


# ═════════════════════════════════════════════════════════════════════
# Handler 4: Resolve stakeholders
# ═════════════════════════════════════════════════════════════════════


class StakeholderHandler(EventHandler):
    name = "stakeholders"

    async def handle(self, ctx: EventContext) -> None:
        if ctx.event_type in ("task.deleted",):
            ctx.skip_external = True
            return

        stakeholders = set()
        if ctx.task.assignee_id:
            stakeholders.add(ctx.task.assignee_id)
        if ctx.task.created_by:
            stakeholders.add(ctx.task.created_by)
        stakeholders.discard(ctx.actor.id)
        ctx.stakeholders = stakeholders


# ═════════════════════════════════════════════════════════════════════
# Handler 5: RabbitMQ publish (with retry for transient failures)
# ═════════════════════════════════════════════════════════════════════


def _publish_sync(routing_key: str, payload: dict):
    try:
        with EventPublisher() as pub:
            pub.publish(routing_key, payload)
    except Exception:
        logger.exception("RabbitMQ publish failed: %s", routing_key)


# These events also send an in-app notification directly (emit_direct_notification),
# so the worker must only use the external channels for them.
EXTERNAL_ONLY = {
    "task.assigned": ["email", "telegram"],
    "task.completed": ["email", "telegram"],
    "task.unblocked": [],
}


class RabbitMQHandler(EventHandler):
    name = "rabbitmq"

    async def should_run(self, ctx: EventContext) -> bool:
        return not ctx.skip_external and bool(ctx.stakeholders)

    async def handle(self, ctx: EventContext) -> None:
        project = await ctx.db.get(Project, ctx.task.project_id)
        project_chat_id = project.telegram_chat_id if project else None

        for user_id in ctx.stakeholders:
            user = await ctx.db.get(User, user_id)
            if not user:
                continue

            payload = {
                **ctx.meta,
                "task_id": str(ctx.task.id),
                "project_id": str(ctx.task.project_id),
                "user_id": str(user.id),
                "email": user.email,
            }
            if ctx.event_type in EXTERNAL_ONLY:
                payload["channels"] = EXTERNAL_ONLY[ctx.event_type]

            if user.telegram_chat_id:
                payload["telegram_chat_id"] = user.telegram_chat_id
            if project_chat_id:
                payload["telegram_chat_id"] = project_chat_id
                member_result = await ctx.db.execute(
                    select(ProjectMember).where(
                        ProjectMember.project_id == ctx.task.project_id,
                        ProjectMember.user_id == user_id,
                    )
                )
                member = member_result.scalars().first()
                if member and member.telegram_thread_id:
                    payload["telegram_thread_id"] = member.telegram_thread_id

            ctx.background_tasks.add_task(_publish_sync, ctx.event_type, payload)


# ═════════════════════════════════════════════════════════════════════
# Pipeline definition — sequential + parallel steps
# ═════════════════════════════════════════════════════════════════════

_pipeline = Pipeline(
    "task_events",
    [
        MetadataHandler(),
        Parallel(AuditLogHandler(), WebSocketHandler()),
        StakeholderHandler(),
        RabbitMQHandler(retry=RetryPolicy(max_retries=1, backoff_base=0.3)),
    ],
)


# ═════════════════════════════════════════════════════════════════════
# Public API
# ═════════════════════════════════════════════════════════════════════


class TaskEventService:
    async def emit(
        self,
        db: AsyncSession,
        background_tasks: BackgroundTasks,
        event_type: str,
        task,
        actor: User,
        extra: Optional[dict] = None,
    ):
        ctx = EventContext(
            db=db,
            background_tasks=background_tasks,
            event_type=event_type,
            task=task,
            actor=actor,
            extra=extra or {},
        )
        await _pipeline.run(ctx)

    async def emit_direct_notification(
        self,
        db: AsyncSession,
        user_id: UUID,
        title_key: str,
        title_params: dict | None = None,
        message_key: str | None = None,
        message_params: dict | None = None,
        type: str = "info",
        entity_type: str = "task",
        entity_id: UUID | None = None,
        project_id: UUID | None = None,
    ):
        await notif_svc.create_and_push(
            db,
            user_id=user_id,
            title_key=title_key,
            title_params=title_params or {},
            message_key=message_key,
            message_params=message_params or {},
            type=type,
            entity_type=entity_type,
            entity_id=entity_id,
            project_id=project_id,
        )


task_events = TaskEventService()
