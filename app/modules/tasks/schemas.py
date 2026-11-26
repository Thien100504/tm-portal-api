from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

TaskStatus = Literal["todo", "in_progress", "review", "done"]
TaskType = Literal["story", "task", "bug"]


def _aware(value: datetime | None) -> datetime | None:
    """Deadlines without a timezone are taken as UTC (the column is timezone-aware)."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


# --- Shared Base Schemas ---
class TaskBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    type: TaskType = "task"
    priority: str = Field(default="medium")
    deadline: datetime | None = None
    estimated_hours: float | None = Field(None, ge=0)
    story_points: int | None = Field(None, ge=0)
    auto_start: bool = False
    epic_id: UUID | None = None

    @field_validator("deadline")
    @classmethod
    def _deadline_utc(cls, value):
        return _aware(value)


# --- Task Dependencies ---
class TaskDependencyCreate(BaseModel):
    depends_on_id: UUID


class TaskDependencyResponse(BaseModel):
    task_id: UUID
    depends_on_id: UUID

    model_config = ConfigDict(from_attributes=True)


# --- Comments ---
class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1)


class CommentResponse(BaseModel):
    id: UUID
    task_id: UUID
    user_id: UUID
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Task Create & Update ---
class TaskCreate(TaskBase):
    project_id: UUID
    status: TaskStatus = "todo"  # the board can create a task directly in a column
    sprint_id: UUID | None = None
    assignee_id: UUID | None = None
    parent_task_id: UUID | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    type: TaskType | None = None
    priority: str | None = None
    deadline: datetime | None = None
    estimated_hours: float | None = Field(None, ge=0)
    story_points: int | None = Field(None, ge=0)
    actual_hours: float | None = Field(None, ge=0)
    position: int | None = None
    sprint_id: UUID | None = None
    epic_id: UUID | None = None
    auto_start: bool | None = None

    @field_validator("deadline")
    @classmethod
    def _deadline_utc(cls, value):
        return _aware(value)


class TaskStatusUpdate(BaseModel):
    status: TaskStatus
    override: bool = False  # For PMs to bypass dependency checks


class TaskPositionUpdate(BaseModel):
    status: TaskStatus
    insert_after_id: UUID | None = None


class CascadeDeadlineRequest(BaseModel):
    delta_days: int


class ImpactedTaskResponse(BaseModel):
    id: UUID
    title: str
    current_deadline: datetime
    new_deadline: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskAssign(BaseModel):
    assignee_id: UUID | None = None


# --- Task Response ---
class TaskResponseBase(TaskBase):
    id: UUID
    project_id: UUID
    workspace_id: UUID | None = None
    sprint_id: UUID | None = None
    parent_task_id: UUID | None = None
    status: str
    assignee_id: UUID | None = None
    created_by: UUID | None = None
    actual_hours: float | None = None
    position: int | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# Includes subtasks and dependencies
class TaskResponse(TaskResponseBase):
    subtasks: list["TaskResponseBase"] = []
    dependencies: list["TaskResponseBase"] = []
    dependent_tasks: list["TaskResponseBase"] = []
    # Not returning full comments in list view to save bandwidth, only in detail if needed


TaskResponse.model_rebuild()
