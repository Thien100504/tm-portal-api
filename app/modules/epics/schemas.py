from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

EpicStatus = Literal["open", "in_progress", "done"]
HEX_COLOR = r"^#[0-9A-Fa-f]{6}$"


class EpicBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    color: Optional[str] = Field(None, pattern=HEX_COLOR)
    status: EpicStatus = "open"
    due_date: Optional[date] = None


class EpicCreate(EpicBase):
    # optional for project epics: they always live in the project's workspace
    workspace_id: Optional[UUID] = None
    project_id: Optional[UUID] = None


class EpicUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    color: Optional[str] = Field(None, pattern=HEX_COLOR)
    status: Optional[EpicStatus] = None
    due_date: Optional[date] = None

    @field_validator("name")
    @classmethod
    def _name_not_null(cls, value):
        if value is None:
            raise ValueError("name cannot be null")
        return value


class EpicResponse(BaseModel):
    # plain types: only input is validated, older rows must still be listed
    name: str
    description: Optional[str] = None
    color: Optional[str] = None
    status: str
    due_date: Optional[date] = None
    id: UUID
    workspace_id: UUID
    project_id: Optional[UUID] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
