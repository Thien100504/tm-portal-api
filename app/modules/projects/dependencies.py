import uuid

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.project import Project
from app.models.user import User
from app.modules.auth.dependencies import get_current_active_user
from app.modules.projects.manager import project_manager


async def get_project_access(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Project:
    """Check that the user can access the project (member or owner)."""
    project = await project_manager.get_project_for_user(
        db, project_id, current_user.id
    )
    if not project:
        raise HTTPException(status_code=403, detail="project.permission_denied")
    return project


from app.modules.rbac.manager import rbac_manager


def require_project_permission(permission_code: str):
    """Dependency factory for dynamic RBAC permission checks."""

    async def permission_checker(
        project_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_active_user),
    ) -> Project:
        project = await project_manager.get_project_for_user(
            db, project_id, current_user.id
        )
        if not project:
            raise HTTPException(status_code=403, detail="project.permission_denied")

        if project.owner_id == current_user.id:
            return project

        has_perm = await rbac_manager.check_permission(
            db,
            current_user.id,
            permission_code=permission_code,
            project_id=project_id,
        )
        if not has_perm:
            raise HTTPException(
                status_code=403, detail=f"project.missing_permission_{permission_code}"
            )

        return project

    return permission_checker


async def get_project_pm_access(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Project:
    """Same as require_project_permission('project.settings')."""
    checker = require_project_permission("project.settings")
    return await checker(project_id, db, current_user)
