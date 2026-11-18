"""
Automation Manager

CRUD operations and the execution engine for IF-THEN automation rules.

Execution flow:
  Task event fires → execute_rules() →
    load active rules matching trigger →
    check conditions →
    apply actions (mutate task in-memory) →
    db.flush() — caller commits
"""

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.automation import AutomationRule
from app.models.task import Task
from app.modules.automation.schemas import (
    AutomationRuleCreate,
    AutomationRuleUpdate,
    VALID_ACTIONS,
    VALID_TRIGGERS,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# CRUD
# ──────────────────────────────────────────────────────────────────────────────


class AutomationManager:
    async def list_by_project(
        self, db: AsyncSession, project_id: uuid.UUID
    ) -> List[AutomationRule]:
        result = await db.execute(
            select(AutomationRule)
            .where(AutomationRule.project_id == project_id)
            .order_by(AutomationRule.created_at.asc())
        )
        return list(result.scalars().all())

    async def get(
        self, db: AsyncSession, rule_id: uuid.UUID
    ) -> Optional[AutomationRule]:
        return await db.get(AutomationRule, rule_id)

    async def create(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
        data: AutomationRuleCreate,
        created_by: uuid.UUID,
    ) -> AutomationRule:
        if data.trigger_event not in VALID_TRIGGERS:
            raise HTTPException(400, "automation.invalid_trigger")
        if data.actions.get("type") not in VALID_ACTIONS:
            raise HTTPException(400, "automation.invalid_action")

        rule = AutomationRule(
            project_id=project_id,
            name=data.name,
            trigger_event=data.trigger_event,
            conditions=data.conditions,
            actions=data.actions,
            is_active=data.is_active,
            created_by=created_by,
        )
        db.add(rule)
        await db.flush()
        await db.refresh(rule)
        return rule

    async def update(
        self,
        db: AsyncSession,
        rule: AutomationRule,
        data: AutomationRuleUpdate,
    ) -> AutomationRule:
        if data.name is not None:
            rule.name = data.name
        if data.conditions is not None:
            rule.conditions = data.conditions
        if data.actions is not None:
            if data.actions.get("type") not in VALID_ACTIONS:
                raise HTTPException(400, "automation.invalid_action")
            rule.actions = data.actions
        if data.is_active is not None:
            rule.is_active = data.is_active
        await db.flush()
        await db.refresh(rule)
        return rule

    async def toggle(self, db: AsyncSession, rule: AutomationRule) -> AutomationRule:
        rule.is_active = not rule.is_active
        await db.flush()
        await db.refresh(rule)
        return rule

    async def delete(self, db: AsyncSession, rule: AutomationRule) -> None:
        await db.delete(rule)
        await db.flush()

    # ──────────────────────────────────────────────────────────────────────────────
    # Execution engine
    # ──────────────────────────────────────────────────────────────────────────────

    async def execute_rules(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
        trigger_event: str,
        task: Task,
        context: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Fire all active rules for this project/trigger, returning number executed.

        context keys:
          old_status, new_status   — for task.status_changed
          old_priority, new_priority — for task.priority_changed
        """
        from app.modules.automation.actions import execute_action

        if context is None:
            context = {}

        result = await db.execute(
            select(AutomationRule).where(
                AutomationRule.project_id == project_id,
                AutomationRule.trigger_event == trigger_event,
                AutomationRule.is_active,
            )
        )
        rules = list(result.scalars().all())

        executed = 0
        for rule in rules:
            try:
                if not _check_conditions(rule.conditions or {}, task, context):
                    continue
                changed = await execute_action(db, rule, task)
                if changed:
                    executed += 1
                    logger.info(
                        "Automation rule '%s' [%s] executed on task %s",
                        rule.name,
                        rule.actions.get("type"),
                        task.id,
                    )
            except Exception:
                logger.exception("Automation rule '%s' failed", rule.name)

        if executed:
            await db.flush()

        return executed


# ──────────────────────────────────────────────────────────────────────────────
# Private helpers
# ──────────────────────────────────────────────────────────────────────────────


def _check_conditions(
    conditions: Dict[str, Any],
    task: Task,
    context: Dict[str, Any],
) -> bool:
    """Return True if all specified conditions are satisfied."""
    if "to_status" in conditions:
        if context.get("new_status") != conditions["to_status"]:
            return False
    if "from_status" in conditions:
        if context.get("old_status") != conditions["from_status"]:
            return False
    if "to_priority" in conditions:
        if context.get("new_priority") != conditions["to_priority"]:
            return False
    if "priority" in conditions:
        if task.priority != conditions["priority"]:
            return False
    return True


# Singleton
automation_manager = AutomationManager()
