import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.modules.auth import schemas, security
from app.modules.auth.dependencies import (
    blacklist_token,
    optional_oauth2_scheme,
    revoke_once,
)
from app.modules.auth.manager import user_manager

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
    Sign in with email and password to get an access token and a refresh token.
    Uses form data (compatible with the OAuth2 flow of Swagger UI).
    Note: form_data.username is the email.

    BR-AUTH-05: lock the account for 15 minutes after 5 failed sign-ins in a row.
    """
    email = form_data.username
    lockout_key = f"login:failed:{email}"

    # ── BR-AUTH-05: check the lockout before querying the DB ───────────
    try:
        r = aioredis.from_url(settings.REDIS_URL)
        attempts = await r.get(lockout_key)
        await r.aclose()
        if attempts and int(attempts) >= 5:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="auth.account_locked",
            )
    except HTTPException:
        raise
    except Exception:
        pass  # fail-open: if Redis is down, sign-in still works

    user = await user_manager.get_by_email(db, email=email)
    if not user or not security.verify_password(form_data.password, user.password_hash):
        # ── Count the failed sign-in ─────────────────────────────────────
        try:
            r = aioredis.from_url(settings.REDIS_URL)
            # Atomic: SET NX EX for first attempt to avoid incr+expire race
            set_result = await r.set(lockout_key, 1, nx=True, ex=900)
            if set_result is None:
                # Key already exists — just increment (TTL already set)
                await r.incr(lockout_key)
            await r.aclose()
        except Exception:
            pass  # fail-open
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="auth.invalid_credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="auth.inactive_user"
        )

    # ── Successful sign-in → reset the failure counter ────────────────
    try:
        r = aioredis.from_url(settings.REDIS_URL)
        await r.delete(lockout_key)
        await r.aclose()
    except Exception:
        pass  # fail-open

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
    try:
        r = aioredis.from_url(settings.REDIS_URL)
        is_blacklisted = await r.exists(f"refresh_blacklist:{request.refresh_token}")
        await r.aclose()
    except Exception:
        is_blacklisted = False  # fail-open: Redis down → allow refresh
    if is_blacklisted:
        raise HTTPException(status_code=401, detail="auth.invalid_token")

    payload = security.decode_token(request.refresh_token)
    if not payload or payload.get("type") != "refresh":
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

    # Token rotation: a refresh token works once. Revoking it is atomic, so two
    # concurrent requests with the same token cannot both get new tokens.
    if not await revoke_once(request.refresh_token, payload):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="auth.invalid_token",
        )
    return {
        "access_token": security.create_access_token(user.id),
        "refresh_token": security.create_refresh_token(user.id),
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    body: schemas.LogoutRequest | None = None,
    token: str | None = Depends(optional_oauth2_scheme),
):
    """
    Log out — blacklist the current access token (if sent) and the refresh token
    (if sent in the body). Blacklisted tokens are rejected until they expire.
    """
    if token:
        payload = security.decode_token(token)
        if payload:
            await blacklist_token(token, payload)
    if body and body.refresh_token:
        refresh_payload = security.decode_token(body.refresh_token)
        if refresh_payload.get("type") == "refresh":
            await blacklist_token(body.refresh_token, refresh_payload)
    return {"detail": "auth.logged_out"}
