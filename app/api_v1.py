"""
API v1 Router Aggregator

Aggregates all v1 module routers in one place.
main.py only needs to include this router.
"""

from fastapi import APIRouter

from app.modules.auth.router import router as auth_router
from app.modules.users.router import router as users_router
from app.modules.notifications.router import router as notifications_router
from app.modules.rbac.router import router as rbac_router

api_v1_router = APIRouter(prefix="/api/v1")

api_v1_router.include_router(
    auth_router, prefix="/auth", tags=["auth"]
)  # /api/v1/auth/...
api_v1_router.include_router(users_router)  # /api/v1/users/...
api_v1_router.include_router(notifications_router)  # /api/v1/notifications/
api_v1_router.include_router(rbac_router)  # /api/v1/roles/...
