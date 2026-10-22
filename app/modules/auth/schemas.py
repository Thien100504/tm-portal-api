import re
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


def check_password_strength(v: str) -> str:
    """Shared password rules: at least one uppercase letter and one digit."""
    if not re.search(r"[A-Z]", v):
        raise ValueError("password.requires_uppercase")
    if not re.search(r"\d", v):
        raise ValueError("password.requires_number")
    return v


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=2, max_length=100)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        return check_password_strength(v)


class UserUpdate(BaseModel):
    """Fields a user may change on their own profile (activation is admin-only)."""

    full_name: Optional[str] = Field(None, min_length=2, max_length=100)
    password: Optional[str] = Field(None, min_length=8)
    avatar_url: Optional[str] = None
    telegram_chat_id: Optional[str] = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: Optional[str]) -> Optional[str]:
        # Only runs when the field is sent; an explicit null is not a valid password
        if v is None:
            raise ValueError("password.required")
        return check_password_strength(v)

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            raise ValueError("user.full_name_required")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    full_name: str
    system_role: str
    avatar_url: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)
