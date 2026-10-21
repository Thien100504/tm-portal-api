"""Unit tests for auth/security.py — pure functions, no DB needed."""

from datetime import timedelta


from app.modules.auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    verify_password,
)


def test_get_password_hash_returns_string():
    hashed = get_password_hash("MyPassword1")
    assert isinstance(hashed, str)
    assert hashed != "MyPassword1"


def test_get_password_hash_different_each_call():
    h1 = get_password_hash("MyPassword1")
    h2 = get_password_hash("MyPassword1")
    assert h1 != h2  # bcrypt uses random salt


def test_verify_password_correct():
    hashed = get_password_hash("MyPassword1")
    assert verify_password("MyPassword1", hashed) is True


def test_verify_password_wrong():
    hashed = get_password_hash("MyPassword1")
    assert verify_password("WrongPass1", hashed) is False


def test_create_access_token_returns_string():
    token = create_access_token("user-id-123")
    assert isinstance(token, str)
    assert len(token) > 0


def test_create_access_token_with_expires_delta():
    token = create_access_token("user-id-123", expires_delta=timedelta(minutes=5))
    assert isinstance(token, str)


def test_create_refresh_token_returns_string():
    token = create_refresh_token("user-id-123")
    assert isinstance(token, str)


def test_create_refresh_token_with_expires_delta():
    token = create_refresh_token("user-id-123", expires_delta=timedelta(days=1))
    assert isinstance(token, str)


def test_decode_token_valid():
    token = create_access_token("user-123")
    payload = decode_token(token)
    assert payload["sub"] == "user-123"
    assert payload["type"] == "access"


def test_decode_token_refresh():
    token = create_refresh_token("user-456")
    payload = decode_token(token)
    assert payload["sub"] == "user-456"
    assert payload["type"] == "refresh"


def test_decode_token_invalid():
    result = decode_token("not.a.valid.token")
    assert result == {}


def test_decode_token_empty():
    result = decode_token("")
    assert result == {}
