import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SprintBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    goal: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: str = Field(default="planning")


class SprintCreate(SprintBase):
    pass


class SprintUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    goal: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[str] = None


class SprintResponse(SprintBase):
    id: uuid.UUID
    project_id: uuid.UUID
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SprintCompleteRequest(BaseModel):
    """Body of POST /sprints/{id}/complete"""

    incomplete_action: str = Field(
        ...,
        description="'backlog' or 'next_sprint'",
        pattern="^(backlog|next_sprint)$",
    )
    target_sprint_id: Optional[uuid.UUID] = Field(
        None,
        description="Required when incomplete_action = 'next_sprint'",
    )


class SprintStats(BaseModel):
    """Completion stats of a sprint"""

    total_tasks: int
    done_tasks: int
    incomplete_tasks: int
    completion_rate: float  # 0-100
    velocity: int  # number of done tasks (= done_tasks)
    actual_days: Optional[int]  # days the sprint actually ran


class BurndownPoint(BaseModel):
    date: str
    ideal_hours: float
    remaining_hours: float
