"""Unit tests for the auth flows: current user, refresh rotation, logout, self-update."""

import asyncio
import importlib
import time
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from jose import jwt
from pydantic import ValidationError

from app.config import get_settings
from app.modules.auth.dependencies import (
    get_current_user,
    get_current_user_from_token,
    require_admin,
)
from app.modules.auth.manager import escape_like, user_manager
from app.modules.auth.schemas import LogoutRequest, RefreshTokenRequest, UserUpdate
from app.modules.auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
)

settings = get_settings()
# the package re-exports `router` (the APIRouter), so load the module itself
auth_router = importlib.import_module("app.modules.auth.router")
REDIS = "app.modules.auth.dependencies.aioredis.from_url"


class FakeRedis:
    """In-memory stand-in for the few Redis commands the auth module uses."""

    def __init__(self):
        self.data = {}
        self.ttl = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, nx=False, ex=None):
        await asyncio.sleep(0)  # yield, like a real network round trip
        if nx and key in self.data:
            return None
        self.data[key], self.ttl[key] = value, ex
        return True

    async def setex(self, key, ttl, value):
        self.data[key], self.ttl[key] = value, ttl

    async def aclose(self):
        pass


@pytest.fixture
def redis():
    fake = FakeRedis()
    with patch(REDIS, return_value=fake):
        yield fake


def _user(**kw):
    data = {"id": uuid.uuid4(), "is_active": True, "system_role": "user"}
    data.update(kw)
    return SimpleNamespace(**data)


def _db(user):
    db = MagicMock()
    db.get = AsyncMock(return_value=user)
    return db


def _blacklisted(redis, token):
    return f"token_blacklist:{token}" in redis.data


# ── tokens ───────────────────────────────────────────────────────────────────
def test_tokens_created_in_the_same_second_are_unique():
    uid = uuid.uuid4()
    assert create_refresh_token(uid) != create_refresh_token(uid)
    assert create_access_token(uid) != create_access_token(uid)
    payload = decode_token(create_access_token(uid))
    assert payload["jti"] and "iat" in payload


def test_access_token_expiry_follows_expires_delta():
    token = create_access_token(uuid.uuid4(), expires_delta=timedelta(minutes=5))
    assert abs(decode_token(token)["exp"] - (time.time() + 300)) < 5


def test_expired_token_is_rejected():
    token = create_access_token(uuid.uuid4(), expires_delta=timedelta(seconds=-1))
    assert decode_token(token) == {}


def test_token_signed_with_other_secret_is_rejected():
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "exp": int(time.time()) + 60},
        "another-secret",
        algorithm=settings.ALGORITHM,
    )
    assert decode_token(forged) == {}


# ── get_current_user ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_current_user_valid_access_token(redis):
    user = _user()
    assert await get_current_user(create_access_token(user.id), _db(user)) is user


@pytest.mark.asyncio
async def test_current_user_rejects_refresh_token(redis):
    user = _user()
    with pytest.raises(HTTPException) as exc:
        await get_current_user(create_refresh_token(user.id), _db(user))
    assert exc.value.status_code == 401
    assert exc.value.detail == "auth.invalid_token"


@pytest.mark.asyncio
async def test_current_user_rejects_blacklisted_token(redis):
    user = _user()
    token = create_access_token(user.id)
    redis.data[f"token_blacklist:{token}"] = "1"
    with pytest.raises(HTTPException) as exc:
        await get_current_user(token, _db(user))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_current_user_inactive_is_forbidden(redis):
    user = _user(is_active=False)
    with pytest.raises(HTTPException) as exc:
        await get_current_user(create_access_token(user.id), _db(user))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_current_user_unknown_user(redis):
    with pytest.raises(HTTPException) as exc:
        await get_current_user(create_access_token(uuid.uuid4()), _db(None))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_current_user_invalid_jwt():
    with pytest.raises(HTTPException) as exc:
        await get_current_user("not-a-jwt", _db(None))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_current_user_redis_down_fails_open():
    user = _user()
    with patch(REDIS, side_effect=ConnectionError):
        assert await get_current_user(create_access_token(user.id), _db(user)) is user


# ── WebSocket token check ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_websocket_accepts_valid_token(redis):
    user = _user()
    assert (
        await get_current_user_from_token(create_access_token(user.id), _db(user))
        is user
    )


@pytest.mark.asyncio
async def test_websocket_rejects_logged_out_token(redis):
    user = _user()
    token = create_access_token(user.id)
    await auth_router.logout(None, token)
    with pytest.raises(HTTPException):
        await get_current_user_from_token(token, _db(user))


# ── require_admin ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_require_admin_allows_admin():
    admin = _user(system_role="admin")
    assert await require_admin(admin) is admin


@pytest.mark.asyncio
async def test_require_admin_blocks_user():
    with pytest.raises(HTTPException) as exc:
        await require_admin(_user(system_role="user"))
    assert exc.value.status_code == 403


# ── /auth/refresh ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_refresh_rotates_and_revokes_old_token(redis):
    user = _user()
    old = create_refresh_token(user.id)
    tokens = await auth_router.refresh_token(
        RefreshTokenRequest(refresh_token=old), _db(user)
    )
    assert decode_token(tokens["access_token"])["type"] == "access"
    assert decode_token(tokens["refresh_token"])["type"] == "refresh"
    assert tokens["refresh_token"] != old
    assert _blacklisted(redis, old)
    assert (
        0
        < redis.ttl[f"token_blacklist:{old}"]
        <= settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
    )


@pytest.mark.asyncio
async def test_refresh_twice_in_the_same_second_keeps_session(redis):
    """Regression: identical tokens made rotation revoke the token it just issued."""
    user = _user()
    db = _db(user)
    first = await auth_router.refresh_token(
        RefreshTokenRequest(refresh_token=create_refresh_token(user.id)), db
    )
    second = await auth_router.refresh_token(
        RefreshTokenRequest(refresh_token=first["refresh_token"]), db
    )
    third = await auth_router.refresh_token(
        RefreshTokenRequest(refresh_token=second["refresh_token"]), db
    )
    assert decode_token(third["refresh_token"])["type"] == "refresh"


@pytest.mark.asyncio
async def test_refresh_token_cannot_be_reused(redis):
    user = _user()
    token = create_refresh_token(user.id)
    await auth_router.refresh_token(RefreshTokenRequest(refresh_token=token), _db(user))
    with pytest.raises(HTTPException) as exc:
        await auth_router.refresh_token(
            RefreshTokenRequest(refresh_token=token), _db(user)
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_concurrent_refresh_with_same_token_only_one_wins(redis):
    user = _user()
    token = create_refresh_token(user.id)
    results = await asyncio.gather(
        *[
            auth_router.refresh_token(
                RefreshTokenRequest(refresh_token=token), _db(user)
            )
            for _ in range(5)
        ],
        return_exceptions=True,
    )
    assert sum(isinstance(r, dict) for r in results) == 1
    assert all(isinstance(r, HTTPException) for r in results if not isinstance(r, dict))


@pytest.mark.asyncio
async def test_refresh_rejects_access_token(redis):
    user = _user()
    with pytest.raises(HTTPException) as exc:
        await auth_router.refresh_token(
            RefreshTokenRequest(refresh_token=create_access_token(user.id)), _db(user)
        )
    assert exc.value.detail == "auth.invalid_token"


@pytest.mark.asyncio
async def test_refresh_rejects_non_uuid_subject(redis):
    token = create_refresh_token("not-a-uuid")
    with pytest.raises(HTTPException) as exc:
        await auth_router.refresh_token(
            RefreshTokenRequest(refresh_token=token), _db(None)
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rejects_inactive_user(redis):
    user = _user(is_active=False)
    with pytest.raises(HTTPException) as exc:
        await auth_router.refresh_token(
            RefreshTokenRequest(refresh_token=create_refresh_token(user.id)), _db(user)
        )
    assert exc.value.detail == "auth.user_inactive"


@pytest.mark.asyncio
async def test_refresh_with_redis_down_still_works():
    user = _user()
    with patch(REDIS, side_effect=ConnectionError):
        tokens = await auth_router.refresh_token(
            RefreshTokenRequest(refresh_token=create_refresh_token(user.id)), _db(user)
        )
    assert decode_token(tokens["access_token"])["type"] == "access"


# ── /auth/logout ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_logout_blacklists_access_and_refresh_tokens(redis):
    uid = uuid.uuid4()
    access, refresh = create_access_token(uid), create_refresh_token(uid)
    result = await auth_router.logout(LogoutRequest(refresh_token=refresh), access)
    assert result == {"detail": "auth.logged_out"}
    assert _blacklisted(redis, access) and _blacklisted(redis, refresh)


@pytest.mark.asyncio
async def test_logout_revoked_refresh_token_cannot_refresh(redis):
    user = _user()
    refresh = create_refresh_token(user.id)
    await auth_router.logout(
        LogoutRequest(refresh_token=refresh), create_access_token(user.id)
    )
    with pytest.raises(HTTPException):
        await auth_router.refresh_token(
            RefreshTokenRequest(refresh_token=refresh), _db(user)
        )


@pytest.mark.asyncio
async def test_logout_without_access_token_still_revokes_refresh_token(redis):
    refresh = create_refresh_token(uuid.uuid4())
    await auth_router.logout(LogoutRequest(refresh_token=refresh), None)
    assert _blacklisted(redis, refresh)


@pytest.mark.asyncio
async def test_logout_ttl_matches_remaining_lifetime(redis):
    access = create_access_token(uuid.uuid4(), expires_delta=timedelta(minutes=10))
    await auth_router.logout(None, access)
    assert (
        590 <= redis.ttl[f"token_blacklist:{access}"] <= 600
    )  # independent of local timezone


@pytest.mark.asyncio
async def test_logout_ignores_access_token_sent_as_refresh(redis):
    uid = uuid.uuid4()
    access, other = create_access_token(uid), create_access_token(uid)
    await auth_router.logout(LogoutRequest(refresh_token=other), access)
    assert _blacklisted(redis, access) and not _blacklisted(redis, other)


@pytest.mark.asyncio
async def test_logout_with_redis_down_still_succeeds():
    with patch(REDIS, side_effect=ConnectionError):
        result = await auth_router.logout(None, create_access_token(uuid.uuid4()))
    assert result == {"detail": "auth.logged_out"}


# ── self-update ──────────────────────────────────────────────────────────────
def test_user_update_rejects_weak_password():
    with pytest.raises(ValidationError):
        UserUpdate(password="a")
    with pytest.raises(ValidationError):
        UserUpdate(password="alllowercase1")


def test_user_update_accepts_strong_password():
    assert UserUpdate(password="Str0ngPass").password == "Str0ngPass"


def test_user_update_rejects_explicit_null():
    with pytest.raises(ValidationError):
        UserUpdate(password=None)
    with pytest.raises(ValidationError):
        UserUpdate(full_name=None)


def test_user_update_omitted_fields_stay_unset():
    assert UserUpdate(full_name="New Name").model_dump(exclude_unset=True) == {
        "full_name": "New Name"
    }


def test_user_update_cannot_change_activation():
    assert "is_active" not in UserUpdate(is_active=False).model_dump()


@pytest.mark.asyncio
async def test_user_manager_update_hashes_new_password():
    user = _user()
    with patch(
        "app.core.base_manager.BaseManager.update", new_callable=AsyncMock
    ) as base_update:
        base_update.return_value = user
        await user_manager.update(
            MagicMock(), db_obj=user, obj_in=UserUpdate(password="N3wPassword")
        )
    data = base_update.await_args.kwargs["obj_in"]
    assert "password" not in data
    assert data["password_hash"].startswith("$2")


# ── search ───────────────────────────────────────────────────────────────────
def test_escape_like_escapes_wildcards():
    assert escape_like("50%_off\\") == "50\\%\\_off\\\\"
    assert escape_like("plain") == "plain"
