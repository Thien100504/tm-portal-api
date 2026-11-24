from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

EpicStatus = Literal["open", "in_progress", "done"]
HEX_COLOR = r"^#[0-9A-Fa-f]{6}$"


class EpicBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    color: str | None = Field(None, pattern=HEX_COLOR)
    status: EpicStatus = "open"
    due_date: date | None = None


class EpicCreate(EpicBase):
    # optional for project epics: they always live in the project's workspace
    workspace_id: UUID | None = None
    project_id: UUID | None = None


class EpicUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    color: str | None = Field(None, pattern=HEX_COLOR)
    status: EpicStatus | None = None
    due_date: date | None = None

    @field_validator("name")
    @classmethod
    def _name_not_null(cls, value):
        if value is None:
            raise ValueError("name cannot be null")
        return value


class EpicResponse(BaseModel):
    # plain types: only input is validated, older rows must still be listed
    name: str
    description: str | None = None
    color: str | None = None
    status: str
    due_date: date | None = None
    id: UUID
    workspace_id: UUID
    project_id: UUID | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
