from datetime import datetime

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.modules.auth import schemas, security
from app.modules.auth.manager import user_manager
from app.modules.auth.dependencies import oauth2_scheme

router = APIRouter()
settings = get_settings()


@router.post(
    "/register",
    response_model=schemas.UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(user_in: schemas.UserCreate, db: AsyncSession = Depends(get_db)):
    """
    Register a new account.
    """
    user = await user_manager.get_by_email(db, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="auth.email_exists",
        )
    user = await user_manager.create(db, obj_in=user_in)
    return user


@router.post("/login", response_model=schemas.TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """
    Log in with email and password to obtain an Access Token and a Refresh Token.
    Uses form-data (compatible with Swagger UI's OAuth2 flow).
    Note: form_data.username is actually the email.
    """
    user = await user_manager.get_by_email(db, email=form_data.username)
    if not user or not security.verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="auth.invalid_credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="auth.inactive_user"
        )

    return {
        "access_token": security.create_access_token(user.id),
        "refresh_token": security.create_refresh_token(user.id),
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post("/refresh", response_model=schemas.TokenResponse)
async def refresh_token(
    request: schemas.RefreshTokenRequest, db: AsyncSession = Depends(get_db)
):
    """
    Use the Refresh Token to obtain a new set of JWTs.
    """
    payload = security.decode_token(request.refresh_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="auth.invalid_token",
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="auth.invalid_token",
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="auth.invalid_token",
        )

    # Load the user from the DB to check active status
    from uuid import UUID

    try:
        user_id = UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="auth.invalid_token"
        )

    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="auth.user_inactive",
        )

    return {
        "access_token": security.create_access_token(user.id),
        "refresh_token": security.create_refresh_token(
            user.id
        ),  # Always issue a new refresh token (Token Rotation)
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(token: str = Depends(oauth2_scheme)):
    """
    Log out — blacklist the current access token in Redis.
    The token will be rejected until it expires naturally.
    """
    payload = security.decode_token(token)
    if payload:
        exp = payload.get("exp", 0)
        ttl = max(int(exp - datetime.utcnow().timestamp()), 0)
        if ttl > 0:
            try:
                r = aioredis.from_url(settings.REDIS_URL)
                await r.setex(f"token_blacklist:{token}", ttl, "1")
                await r.aclose()
            except Exception:
                pass
    return {"detail": "auth.logged_out"}
