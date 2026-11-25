from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr


class AdminUserResponse(BaseModel):
    id: UUID
    email: str
    full_name: str
    system_role: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminUserUpdate(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None


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

    model_config = ConfigDict(from_attributes=True)
