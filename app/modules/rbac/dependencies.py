from typing import Optional
import uuid
from fastapi import Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.user import User
from app.modules.auth.dependencies import get_current_active_user
from app.modules.rbac.manager import rbac_manager


def require_permission(permission_code: str):
    """
    Dependency factory for RBAC permission checks.
    Usage: Depends(require_permission("task.create"))
    Needs workspace_id (query) or project_id (query) to determine the scope.
    """

    async def permission_checker(
        workspace_id: Optional[uuid.UUID] = Query(None),
        project_id: Optional[uuid.UUID] = Query(None),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_active_user),
    ):
        if not workspace_id and not project_id:
            raise HTTPException(status_code=400, detail="rbac.missing_scope")

        has_perm = await rbac_manager.check_permission(
            db,
            user_id=current_user.id,
            permission_code=permission_code,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        if not has_perm:
            raise HTTPException(status_code=403, detail="rbac.permission_denied")

        return True

    return permission_checker
