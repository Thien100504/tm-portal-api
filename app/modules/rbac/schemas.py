import uuid
from typing import List, Optional
from pydantic import BaseModel, Field


class PermissionResponse(BaseModel):
    id: uuid.UUID
    code: str
    module: str
    description: Optional[str] = None

    class Config:
        from_attributes = True


class RoleBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None


class RoleCreate(RoleBase):
    scope: str = Field(default="project")
    workspace_id: Optional[uuid.UUID] = None


class RoleUpdate(RoleBase):
    pass


class RoleUpdatePermissions(BaseModel):
    permission_ids: List[uuid.UUID]


class RoleResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    scope: str
    workspace_id: Optional[uuid.UUID] = None
    is_system_default: bool
    permissions: List[PermissionResponse] = []

    class Config:
        from_attributes = True
