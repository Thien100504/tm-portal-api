from pydantic import BaseModel, Field, EmailStr
from uuid import UUID
from datetime import datetime
from typing import Optional, Dict, Any


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
    settings: Optional[WorkspaceSettings] = None


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    settings: Optional[WorkspaceSettings] = None


class WorkspaceResponse(BaseModel):
    id: UUID
    name: str
    type: str
    owner_id: UUID
    settings: Dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


from app.modules.auth.schemas import UserResponse
from app.modules.rbac.schemas import RoleResponse


class WorkspaceMemberInvite(BaseModel):
    email: EmailStr
    role_id: Optional[UUID] = None


class WorkspaceMemberUpdate(BaseModel):
    role_id: Optional[UUID] = None


class WorkspaceMemberResponse(BaseModel):
    workspace_id: UUID
    user_id: UUID
    role_id: Optional[UUID] = None
    role: Optional[RoleResponse] = None
    user: Optional[UserResponse] = None
    created_at: datetime

    class Config:
        from_attributes = True


class WorkspaceInvitationResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    email: str
    role_id: Optional[UUID] = None
    role: Optional[RoleResponse] = None
    status: str
    expires_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True
