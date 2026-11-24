from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class WorkspaceSettings(BaseModel):
    enable_members: bool = False
    enable_sprint: bool = False
    enable_epics: bool = False
    enable_story_points: bool = False
    enable_workload: bool = False
    enable_automation: bool = False
    enable_ai: bool = True
    enable_time_tracking: bool = False
    enable_calendar: bool = True
    enable_list_view: bool = False
    enable_reports: bool = False
    theme: str = "minimal"


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    type: str = Field("personal", pattern="^(personal|team)$")
    settings: WorkspaceSettings | None = None


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=100)
    settings: WorkspaceSettings | None = None


class WorkspaceResponse(BaseModel):
    id: UUID
    name: str
    type: str
    owner_id: UUID
    settings: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


from app.modules.auth.schemas import UserResponse
from app.modules.rbac.schemas import RoleResponse


class WorkspaceMemberInvite(BaseModel):
    email: EmailStr
    role_id: UUID | None = None


class WorkspaceMemberUpdate(BaseModel):
    role_id: UUID | None = None


class WorkspaceMemberResponse(BaseModel):
    workspace_id: UUID
    user_id: UUID
    role_id: UUID | None = None
    role: RoleResponse | None = None
    user: UserResponse | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkspaceInvitationResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    email: str
    role_id: UUID | None = None
    role: RoleResponse | None = None
    status: str
    expires_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
