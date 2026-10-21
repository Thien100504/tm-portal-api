from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# --- Shared Base Schemas ---
class TaskBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    priority: str = Field(default="medium")
    deadline: Optional[datetime] = None
    estimated_hours: Optional[float] = Field(None, ge=0)
    story_points: Optional[int] = Field(None, ge=0)
    auto_start: bool = False
    epic_id: Optional[UUID] = None


# --- Task Dependencies ---
class TaskDependencyCreate(BaseModel):
    depends_on_id: UUID


class TaskDependencyResponse(BaseModel):
    task_id: UUID
    depends_on_id: UUID

    class Config:
        from_attributes = True


# --- Comments ---
class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1)


class CommentResponse(BaseModel):
    id: UUID
    task_id: UUID
    user_id: UUID
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


# --- Task Create & Update ---
class TaskCreate(TaskBase):
    project_id: UUID
    sprint_id: Optional[UUID] = None
    assignee_id: Optional[UUID] = None
    parent_task_id: Optional[UUID] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    priority: Optional[str] = None
    deadline: Optional[datetime] = None
    estimated_hours: Optional[float] = Field(None, ge=0)
    story_points: Optional[int] = Field(None, ge=0)
    actual_hours: Optional[float] = Field(None, ge=0)
    position: Optional[int] = None
    sprint_id: Optional[UUID] = None
    epic_id: Optional[UUID] = None
    auto_start: Optional[bool] = None


class TaskStatusUpdate(BaseModel):
    status: str
    override: bool = False  # For PMs to bypass dependency checks


class TaskPositionUpdate(BaseModel):
    status: str
    insert_after_id: Optional[UUID] = None


class CascadeDeadlineRequest(BaseModel):
    delta_days: int


class ImpactedTaskResponse(BaseModel):
    id: UUID
    title: str
    current_deadline: datetime
    new_deadline: datetime

    class Config:
        from_attributes = True


class TaskAssign(BaseModel):
    assignee_id: Optional[UUID] = None


# --- Task Response ---
class TaskResponseBase(TaskBase):
    id: UUID
    project_id: UUID
    workspace_id: Optional[UUID] = None
    sprint_id: Optional[UUID] = None
    parent_task_id: Optional[UUID] = None
    status: str
    assignee_id: Optional[UUID] = None
    created_by: Optional[UUID] = None
    actual_hours: Optional[float] = None
    position: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Includes subtasks and dependencies
class TaskResponse(TaskResponseBase):
    subtasks: List["TaskResponseBase"] = []
    dependencies: List["TaskResponseBase"] = []
    dependent_tasks: List["TaskResponseBase"] = []
    # Not returning full comments in list view to save bandwidth, only in detail if needed


TaskResponse.model_rebuild()
