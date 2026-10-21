from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class EpicBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    color: Optional[str] = Field(None, max_length=50)
    status: str = Field(default="open")
    due_date: Optional[date] = None


class EpicCreate(EpicBase):
    workspace_id: UUID
    project_id: Optional[UUID] = None


class EpicUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    color: Optional[str] = Field(None, max_length=50)
    status: Optional[str] = None
    due_date: Optional[date] = None


class EpicResponse(EpicBase):
    id: UUID
    workspace_id: UUID
    project_id: Optional[UUID] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
