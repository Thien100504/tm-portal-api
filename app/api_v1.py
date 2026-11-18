"""
API v1 Router Aggregator

Aggregates all v1 module routers in one place.
main.py only needs to include this router.
"""

from fastapi import APIRouter

from app.modules.auth.router import router as auth_router
from app.modules.users.router import router as users_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.projects.router import router as project_router
from app.modules.sprints.router import router as sprint_router
from app.modules.tasks.router import router as task_router
from app.modules.ai.router import router as ai_router
from app.modules.automation.router import router as automation_router
from app.modules.notifications.router import router as notifications_router
from app.modules.admin.router import router as admin_router
from app.modules.workspaces.router import router as workspace_router
from app.modules.epics.router import router as epic_router
from app.modules.rbac.router import router as rbac_router

api_v1_router = APIRouter(prefix="/api/v1")

api_v1_router.include_router(
    auth_router, prefix="/auth", tags=["auth"]
)  # /api/v1/auth/...
api_v1_router.include_router(users_router)  # /api/v1/users/...
api_v1_router.include_router(dashboard_router)  # /api/v1/dashboard/...
api_v1_router.include_router(project_router)  # /api/v1/projects/...
api_v1_router.include_router(sprint_router)  # /api/v1/projects/{id}/sprints/...
api_v1_router.include_router(task_router)  # /api/v1/tasks/...
api_v1_router.include_router(ai_router)  # /api/v1/projects/{id}/ai-insights/
api_v1_router.include_router(automation_router)  # /api/v1/projects/{id}/automations/
api_v1_router.include_router(notifications_router)  # /api/v1/notifications/
api_v1_router.include_router(admin_router)  # /api/v1/admin/...
api_v1_router.include_router(workspace_router)  # /api/v1/workspaces/...
api_v1_router.include_router(epic_router)  # /api/v1/epics/...
api_v1_router.include_router(rbac_router)  # /api/v1/roles/...
