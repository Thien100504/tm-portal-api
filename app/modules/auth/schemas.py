import re
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=2, max_length=100)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("password.requires_uppercase")
        if not re.search(r"\d", v):
            raise ValueError("password.requires_number")
        return v


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    password: Optional[str] = None
    avatar_url: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    is_active: Optional[bool] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


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

    class Config:
        from_attributes = True
