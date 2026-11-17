"""
Automation Action Registry — each action type is a handler class.

Adding a new action:
  1. Create class inheriting ActionHandler
  2. Register in ACTION_REGISTRY at bottom
  3. Add action type to schemas.VALID_ACTIONS
  Done — no if/elif chains to edit.
"""

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.events.publisher import EventPublisher
from app.models.automation import AutomationRule
from app.models.task import Task

logger = logging.getLogger(__name__)


class ActionHandler:
    """Base class for automation actions."""

    name: str = "base"

    async def execute(
        self, db: AsyncSession, rule: AutomationRule, task: Task, value: Any
    ) -> bool:
        raise NotImplementedError


# ═════════════════════════════════════════════════════════════════════
# Task mutation actions
# ═════════════════════════════════════════════════════════════════════


class SetStatusAction(ActionHandler):
    name = "set_status"

    async def execute(self, db, rule, task, value):
        valid = {"todo", "in_progress", "review", "done"}
        if value in valid and task.status != value:
            task.status = value
            return True
        return False


class SetPriorityAction(ActionHandler):
    name = "set_priority"

    async def execute(self, db, rule, task, value):
        valid = {"low", "medium", "high"}
        if value in valid and task.priority != value:
            task.priority = value
            return True
        return False


class AssignToSprintAction(ActionHandler):
    name = "assign_to_sprint"

    async def execute(self, db, rule, task, value):
        if not value:
            return False
        try:
            sprint_id = uuid.UUID(str(value))
        except ValueError:
            logger.debug("Invalid UUID for assign_to_sprint: %s", value)
            return False

        from app.models.sprint import Sprint

        sprint = await db.get(Sprint, sprint_id)
        if sprint and sprint.project_id == task.project_id and not sprint.is_deleted:
            if task.sprint_id != sprint_id:
                task.sprint_id = sprint_id
                return True
        return False


class RemoveFromSprintAction(ActionHandler):
    name = "remove_from_sprint"

    async def execute(self, db, rule, task, value):
        if task.sprint_id is not None:
            task.sprint_id = None
            return True
        return False


class SetDeadlineAction(ActionHandler):
    name = "set_deadline"

    async def execute(self, db, rule, task, value):
        try:
            days = int(value)
            from datetime import timedelta, datetime, timezone

            task.deadline = datetime.now(timezone.utc) + timedelta(days=days)
            return True
        except (ValueError, TypeError):
            return False


# ═════════════════════════════════════════════════════════════════════
# Notification actions
# ═════════════════════════════════════════════════════════════════════


class ReassignAction(ActionHandler):
    name = "reassign"

    async def execute(self, db, rule, task, value):
        if not value:
            return False
        try:
            user_id = uuid.UUID(str(value))
        except ValueError:
            logger.debug("Invalid UUID for reassign: %s", value)
            return False

        if task.assignee_id == user_id:
            return False

        # Only live members of the project can be assigned by a rule
        from sqlalchemy import select

        from app.models.project import ProjectMember

        member = await db.scalar(
            select(ProjectMember.user_id).where(
                ProjectMember.project_id == task.project_id,
                ProjectMember.user_id == user_id,
                ProjectMember.is_deleted.is_(False),
            )
        )
        if not member:
            logger.info(
                "Rule '%s' skipped: %s is not a project member", rule.name, user_id
            )
            return False

        task.assignee_id = user_id
        from app.modules.notifications import service as notif_svc

        await notif_svc.create_and_push(
            db,
            user_id=user_id,
            title_key="notification.task.assigned",
            title_params={"title": task.title[:60]},
            message_key="notification.automation.assigned_by_rule",
            message_params={"rule": rule.name},
            type="assignment",
            entity_type="task",
            entity_id=task.id,
            project_id=task.project_id,
        )
        logger.info(
            "Reassigned task %s to user %s via rule '%s'", task.id, user_id, rule.name
        )
        return True


class AddCommentAction(ActionHandler):
    name = "add_comment"

    async def execute(self, db, rule, task, value):
        if not value:
            return False
        from app.models.task import Comment

        comment = Comment(
            task_id=task.id,
            user_id=rule.created_by,
            content=str(value),
        )
        db.add(comment)
        return True


class SendCustomNotificationAction(ActionHandler):
    name = "send_custom_notification"

    async def execute(self, db, rule, task, value):
        if not value or not task.assignee_id:
            return False
        try:
            from app.modules.notifications import service as notif_svc

            await notif_svc.create_and_push(
                db,
                user_id=task.assignee_id,
                title_key="notification.automation.custom",
                title_params={"rule": rule.name},
                message_key="notification.automation.custom_message",
                message_params={"message": str(value)},
                type="automation",
                entity_type="task",
                entity_id=task.id,
                project_id=task.project_id,
            )
            logger.info(
                "Sent custom notification for task %s via rule '%s'", task.id, rule.name
            )
            return True
        except Exception:
            logger.exception("Failed send_custom_notification for task %s", task.id)
            return False


# ═════════════════════════════════════════════════════════════════════
# AI actions (publish to RabbitMQ)
# ═════════════════════════════════════════════════════════════════════


class _AIAction(ActionHandler):
    """Base for AI actions that publish to RabbitMQ."""

    routing_key: str = ""

    async def execute(self, db, rule, task, value):
        try:
            with EventPublisher() as pub:
                pub.publish(
                    self.routing_key,
                    {
                        "task_id": str(task.id),
                        "title": task.title,
                        "description": task.description or "",
                        "project_id": str(task.project_id),
                        "actor_id": str(rule.created_by) if rule.created_by else None,
                    },
                )
            logger.info(
                "Published %s for task %s via rule '%s'",
                self.routing_key,
                task.id,
                rule.name,
            )
            return True
        except Exception:
            logger.exception(
                "Failed to publish %s for task %s", self.routing_key, task.id
            )
            return False


class AIGenerateSubtasksAction(_AIAction):
    name = "ai_generate_subtasks"
    routing_key = "task.ai.breakdown"


class AIAutoEstimateAction(_AIAction):
    name = "ai_auto_estimate"
    routing_key = "task.ai.estimate"


# ═════════════════════════════════════════════════════════════════════
# Registry — THE SINGLE PLACE to register all actions
# ═════════════════════════════════════════════════════════════════════

_ALL_ACTIONS = [
    SetStatusAction(),
    SetPriorityAction(),
    AssignToSprintAction(),
    RemoveFromSprintAction(),
    SetDeadlineAction(),
    ReassignAction(),
    AddCommentAction(),
    SendCustomNotificationAction(),
    AIGenerateSubtasksAction(),
    AIAutoEstimateAction(),
]

ACTION_REGISTRY: dict[str, ActionHandler] = {a.name: a for a in _ALL_ACTIONS}


async def execute_action(db: AsyncSession, rule: AutomationRule, task: Task) -> bool:
    """Look up and run the action handler. Returns True if anything changed."""
    action_type: str | None = rule.actions.get("type")
    value = rule.actions.get("value")

    handler = ACTION_REGISTRY.get(action_type or "")
    if not handler:
        logger.warning("Unknown automation action type: %s", action_type)
        return False

    return await handler.execute(db, rule, task, value)
