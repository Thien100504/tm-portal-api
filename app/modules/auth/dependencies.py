import logging
from typing import Optional
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
    try:
        settings = get_settings()
        r = aioredis.from_url(settings.REDIS_URL)
        is_blacklisted = await r.get(f"token_blacklist:{token}")
        await r.aclose()
        if is_blacklisted:
            raise credentials_exception
    except HTTPException:
        raise
    except Exception:
        logger.debug("Redis blacklist check skipped (connection unavailable)")

    user_id_str: Optional[str] = payload.get("sub")
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
    """Alias for get_current_user, since get_current_user already checks is_active."""
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

    user_id_str: Optional[str] = payload.get("sub")
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
