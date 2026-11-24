import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PermissionResponse(BaseModel):
    id: uuid.UUID
    code: str
    module: str
    description: str | None = None

    model_config = ConfigDict(from_attributes=True)


class RoleBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None


class RoleCreate(RoleBase):
    scope: Literal["workspace", "project"] = "project"
    workspace_id: uuid.UUID | None = None


class RoleUpdate(RoleBase):
    pass


class RoleUpdatePermissions(BaseModel):
    permission_ids: list[uuid.UUID]


class RoleResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    scope: str
    workspace_id: uuid.UUID | None = None
    is_system_default: bool
    permissions: list[PermissionResponse] = []

    model_config = ConfigDict(from_attributes=True)
