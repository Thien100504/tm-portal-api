"""Unit tests for auth schemas validation."""

import uuid

import pytest
from pydantic import ValidationError

from app.modules.auth.schemas import (
    RefreshTokenRequest,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
    UserUpdate,
)


def test_user_create_valid():
    user = UserCreate(
        email="test@example.com", password="Password1", full_name="Test User"
    )
    assert user.email == "test@example.com"
    assert user.full_name == "Test User"


def test_user_create_invalid_email():
    with pytest.raises(ValidationError):
        UserCreate(email="not-an-email", password="Password1", full_name="Test User")


def test_user_create_password_too_short():
    with pytest.raises(ValidationError):
        UserCreate(email="test@example.com", password="Pa1", full_name="Test User")


def test_user_create_password_no_uppercase():
    with pytest.raises(ValidationError):
        UserCreate(
            email="test@example.com", password="password1", full_name="Test User"
        )


def test_user_create_password_no_number():
    with pytest.raises(ValidationError):
        UserCreate(email="test@example.com", password="Password", full_name="Test User")


def test_user_create_full_name_too_short():
    with pytest.raises(ValidationError):
        UserCreate(email="test@example.com", password="Password1", full_name="A")


def test_user_login_valid():
    login = UserLogin(email="test@example.com", password="anypassword")
    assert login.email == "test@example.com"


def test_user_update_optional_fields():
    update = UserUpdate()
    assert update.full_name is None
    assert update.password is None


def test_user_update_with_fields():
    update = UserUpdate(full_name="New Name", is_active=False)
    assert update.full_name == "New Name"
    assert "is_active" not in update.model_dump()  # activation is admin-only


def test_token_response():
    token = TokenResponse(
        access_token="access123",
        refresh_token="refresh456",
        expires_in=900,
    )
    assert token.token_type == "bearer"
    assert token.expires_in == 900


def test_refresh_token_request():
    req = RefreshTokenRequest(refresh_token="some-token")
    assert req.refresh_token == "some-token"


def test_user_response_from_attributes():
    user_id = uuid.uuid4()
    resp = UserResponse(
        id=user_id,
        email="test@example.com",
        full_name="Test User",
        system_role="user",
        is_active=True,
    )
    assert resp.id == user_id
    assert resp.avatar_url is None
