"""
Notifications Router — proxies to Notification microservice.

GET  /api/v1/notifications/              list (paginated)
GET  /api/v1/notifications/unread-count  badge number
PATCH /api/v1/notifications/read-all     mark all as read
PATCH /api/v1/notifications/{id}/read    mark one as read
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.modules.auth.dependencies import get_current_active_user
from app.modules.notifications import service as notif_svc

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return await notif_svc.get_for_user(db, current_user.id, limit=limit, offset=offset)


@router.get("/unread-count")
async def unread_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    count = await notif_svc.get_unread_count(db, current_user.id)
    return {"count": count}


@router.patch("/read-all")
async def read_all(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    updated = await notif_svc.mark_all_read(db, current_user.id)
    return {"marked_read": updated}


@router.patch("/{notif_id}/read")
async def read_one(
    notif_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    ok = await notif_svc.mark_read(db, notif_id, current_user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="notification.not_found")
    return {"id": str(notif_id), "is_read": True}
