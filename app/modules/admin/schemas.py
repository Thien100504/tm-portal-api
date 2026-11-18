from pydantic import BaseModel, EmailStr
from uuid import UUID
from datetime import datetime
from typing import Optional


class AdminUserResponse(BaseModel):
    id: UUID
    email: str
    full_name: str
    system_role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class AdminUserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None


class WorkspaceAdminResponse(BaseModel):
    id: UUID
    name: str
    type: str
    owner_name: str
    owner_email: str
    projects_count: int
    tasks_count: int
    members_count: int
    created_at: datetime

    class Config:
        from_attributes = True
