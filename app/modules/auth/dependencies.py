import logging
import time
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.modules.auth.security import decode_token

logger = logging.getLogger(__name__)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
# Same scheme, but a missing Authorization header is not an error (used by logout)
optional_oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login", auto_error=False
)

BLACKLIST_PREFIX = "token_blacklist:"


def _remaining_ttl(payload: dict) -> int:
    """Seconds until the token expires (jose encodes exp as a UTC timestamp)."""
    return max(int(payload.get("exp", 0) - time.time()), 0)


async def _close(r) -> None:
    try:
        await r.aclose()
    except Exception:
        pass


async def is_token_blacklisted(token: str) -> bool:
    """Check the Redis blacklist. Fails open (returns False) if Redis is down."""
    r = None
    try:
        r = aioredis.from_url(get_settings().REDIS_URL)
        return bool(await r.get(f"{BLACKLIST_PREFIX}{token}"))
    except Exception:
        logger.warning("Redis unavailable: token blacklist check skipped")
        return False
    finally:
        if r is not None:
            await _close(r)


async def blacklist_token(token: str, payload: dict) -> None:
    """Blacklist a token until it expires. Logs a warning if Redis is down."""
    ttl = _remaining_ttl(payload)
    if ttl <= 0:
        return
    r = None
    try:
        r = aioredis.from_url(get_settings().REDIS_URL)
        await r.setex(f"{BLACKLIST_PREFIX}{token}", ttl, "1")
    except Exception:
        logger.warning("Redis unavailable: token could not be blacklisted")
    finally:
        if r is not None:
            await _close(r)


async def revoke_once(token: str, payload: dict) -> bool:
    """
    Atomically blacklist a one-time token (SET NX EX).

    Returns False if the token was already revoked, so two concurrent requests
    with the same refresh token cannot both succeed. Fails open if Redis is down.
    """
    ttl = _remaining_ttl(payload)
    if ttl <= 0:
        return False
    r = None
    try:
        r = aioredis.from_url(get_settings().REDIS_URL)
        return bool(await r.set(f"{BLACKLIST_PREFIX}{token}", "1", nx=True, ex=ttl))
    except Exception:
        logger.warning("Redis unavailable: refresh token rotation is not enforced")
        return True
    finally:
        if r is not None:
            await _close(r)


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)
) -> User:
    """Dependency that resolves the current user from the access token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="auth.invalid_credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_token(token)
    if not payload:
        raise credentials_exception

    token_type: str = payload.get("type", "")
    if token_type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="auth.invalid_token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check Redis blacklist (fail-open if Redis is down)
    if await is_token_blacklisted(token):
        raise credentials_exception

    user_id_str: str | None = payload.get("sub")
    if user_id_str is None:
        raise credentials_exception

    try:
        user_id = UUID(user_id_str)
    except ValueError:
        raise credentials_exception

    user = await db.get(User, user_id)
    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="auth.inactive_user"
        )

    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency that only allows Admins."""
    if current_user.system_role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin.access_forbidden",
        )
    return current_user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Alias of get_current_user, which already checks is_active."""
    return current_user


async def get_current_user_from_token(token: str, db: AsyncSession) -> User:
    """
    Used by the WebSocket endpoint — does not use Depends, takes the token and db directly.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="auth.invalid_credentials",
    )

    payload = decode_token(token)
    if not payload:
        raise credentials_exception

    if payload.get("type") != "access":
        raise credentials_exception

    # A logged-out (blacklisted) token must not open a WebSocket either
    if await is_token_blacklisted(token):
        raise credentials_exception

    user_id_str: str | None = payload.get("sub")
    if not user_id_str:
        raise credentials_exception

    try:
        user_id = UUID(user_id_str)
    except ValueError:
        raise credentials_exception

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_exception

    return user
