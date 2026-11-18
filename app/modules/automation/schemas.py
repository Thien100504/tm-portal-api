"""
Automation Schemas

Pydantic models for the automation rules endpoints.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Supported trigger events ──────────────────────────────────────────────────
VALID_TRIGGERS = {
    "task.created",
    "task.status_changed",
    "task.assigned",
    "task.priority_changed",
    "task.unblocked",
    "task.due_soon",
    "task.overdue",
    "task.stale",
}

# ── Supported action types ────────────────────────────────────────────────────
VALID_ACTIONS = {
    "set_status",
    "set_priority",
    "assign_to_sprint",
    "remove_from_sprint",
    "add_comment",
    "reassign",
    "ai_generate_subtasks",
    "ai_auto_estimate",
    "set_deadline",
    "send_custom_notification",
}


class AutomationRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    trigger_event: str = Field(
        ...,
        description="task.created | task.status_changed | task.assigned | task.priority_changed | task.unblocked | task.due_soon | task.overdue | task.stale",
    )
    conditions: Optional[Dict[str, Any]] = Field(
        None,
        description="Optional filters: to_status, from_status, priority, to_priority",
    )
    actions: Dict[str, Any] = Field(
        ...,
        description='{"type": "set_status|set_priority|assign_to_sprint|remove_from_sprint|add_comment|reassign|ai_generate_subtasks|ai_auto_estimate|set_deadline|send_custom_notification", "value": "..."}',
    )
    is_active: bool = True


class AutomationRuleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    conditions: Optional[Dict[str, Any]] = None
    actions: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class AutomationRuleResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    trigger_event: str
    conditions: Optional[Dict[str, Any]]
    actions: Dict[str, Any]
    is_active: bool
    created_by: Optional[uuid.UUID]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
