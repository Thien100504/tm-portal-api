import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    status: str = Field(default="active")
    start_date: date | None = None
    end_date: date | None = None
    telegram_chat_id: str | None = None
    workspace_id: uuid.UUID | None = None
    type: str = Field(default="standard")


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    status: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    telegram_chat_id: str | None = None
    type: str | None = None


class ProjectResponse(ProjectBase):
    id: uuid.UUID
    owner_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    member_count: int = Field(default=1)
    members: list["ProjectMemberResponse"] = []

    model_config = ConfigDict(from_attributes=True)


from pydantic import BaseModel, ConfigDict, Field

from app.modules.auth.schemas import UserResponse


class RoleResponse(BaseModel):
    id: uuid.UUID
    name: str
    scope: str
    is_system_default: bool
    model_config = ConfigDict(from_attributes=True)


class ProjectMemberCreate(BaseModel):
    user_id: uuid.UUID
    project_role: str = Field(default="viewer")
    role_id: uuid.UUID | None = None


class ProjectMemberUpdate(BaseModel):
    project_role: str | None = None
    role_id: uuid.UUID | None = None
    telegram_thread_id: str | None = None


class ProjectMemberResponse(BaseModel):
    project_id: uuid.UUID
    user_id: uuid.UUID
    project_role: str
    role_id: uuid.UUID | None = None
    role: RoleResponse | None = None
    joined_at: datetime
    telegram_thread_id: str | None = None
    user: UserResponse | None = None

    model_config = ConfigDict(from_attributes=True)


ProjectResponse.model_rebuild()
