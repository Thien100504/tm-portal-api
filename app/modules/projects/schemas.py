import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ProjectBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    status: str = Field(default="active")
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    telegram_chat_id: Optional[str] = None
    workspace_id: Optional[uuid.UUID] = None
    type: str = Field(default="standard")


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    telegram_chat_id: Optional[str] = None
    type: Optional[str] = None


class ProjectResponse(ProjectBase):
    id: uuid.UUID
    owner_id: Optional[uuid.UUID]
    created_at: datetime
    updated_at: datetime
    member_count: int = Field(default=1)
    members: list["ProjectMemberResponse"] = []

    model_config = ConfigDict(from_attributes=True)


from app.modules.auth.schemas import UserResponse
from pydantic import BaseModel, ConfigDict, Field


class RoleResponse(BaseModel):
    id: uuid.UUID
    name: str
    scope: str
    is_system_default: bool
    model_config = ConfigDict(from_attributes=True)


class ProjectMemberCreate(BaseModel):
    user_id: uuid.UUID
    project_role: str = Field(default="viewer")
    role_id: Optional[uuid.UUID] = None


class ProjectMemberUpdate(BaseModel):
    project_role: Optional[str] = None
    role_id: Optional[uuid.UUID] = None
    telegram_thread_id: Optional[str] = None


class ProjectMemberResponse(BaseModel):
    project_id: uuid.UUID
    user_id: uuid.UUID
    project_role: str
    role_id: Optional[uuid.UUID] = None
    role: Optional[RoleResponse] = None
    joined_at: datetime
    telegram_thread_id: Optional[str] = None
    user: Optional[UserResponse] = None

    model_config = ConfigDict(from_attributes=True)


ProjectResponse.model_rebuild()
