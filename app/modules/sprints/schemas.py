import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_SPRINT_DAYS = 365


def check_sprint_dates(start: date | None, end: date | None) -> str | None:
    """Error code when the planned dates are inconsistent, else None."""
    if start and end:
        if end < start:
            return "sprint.error_end_before_start"
        if (end - start).days > MAX_SPRINT_DAYS:
            return "sprint.error_too_long"
    return None


class SprintBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    goal: str | None = None
    start_date: date | None = None
    end_date: date | None = None


class SprintCreate(SprintBase):
    # status is not accepted: it only changes through start / complete / reopen

    @model_validator(mode="after")
    def _dates(self):
        error = check_sprint_dates(self.start_date, self.end_date)
        if error:
            raise ValueError(error)
        return self


class SprintUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    goal: str | None = None
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("name")
    @classmethod
    def _name_not_null(cls, value):
        if value is None:
            raise ValueError("name cannot be null")
        return value


class SprintResponse(SprintBase):
    id: uuid.UUID
    status: str
    project_id: uuid.UUID
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class SprintCompleteRequest(BaseModel):
    """Body of POST /sprints/{id}/complete"""

    incomplete_action: str = Field(
        ...,
        description="'backlog' or 'next_sprint'",
        pattern="^(backlog|next_sprint)$",
    )
    target_sprint_id: uuid.UUID | None = Field(
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
    actual_days: int | None  # days the sprint actually ran


class BurndownPoint(BaseModel):
    date: str
    ideal_hours: float
    remaining_hours: float
