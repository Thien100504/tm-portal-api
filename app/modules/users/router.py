from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.modules.auth import schemas
from app.modules.auth.dependencies import get_current_active_user
from app.modules.auth.manager import user_manager

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/search", response_model=list[schemas.UserResponse])
async def search_users(
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Search users by email or name."""
    return await user_manager.search_users(db, q)


@router.get("/me", response_model=schemas.UserResponse)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    """
    Get the currently logged-in User.
    """
    return current_user


@router.put("/me", response_model=schemas.UserResponse)
async def update_users_me(
    user_in: schemas.UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Update the currently logged-in User (name, password, etc.)
    """
    updated_user = await user_manager.update(db, db_obj=current_user, obj_in=user_in)
    return updated_user
