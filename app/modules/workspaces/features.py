import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.automation import AutomationRule
from app.models.epic import Epic
from app.models.project import Project
from app.models.sprint import Sprint
from app.models.task import Task
from app.models.workspace import Workspace


def require_feature(feature_key: str):
    """
    Dependency to check if a feature flag is enabled for the workspace.
    It automatically inspects path parameters to find workspace_id, project_id, sprint_id, etc.
    """

    async def feature_checker(request: Request, db: AsyncSession = Depends(get_db)):
        workspace_id = request.path_params.get("workspace_id")
        project_id = request.path_params.get("project_id")
        sprint_id = request.path_params.get("sprint_id")
        task_id = request.path_params.get("task_id")
        rule_id = request.path_params.get("rule_id")  # For automations
        epic_id = request.path_params.get("epic_id")

        if not workspace_id:
            if project_id:
                project = await db.get(Project, uuid.UUID(project_id))
                if project:
                    workspace_id = project.workspace_id
            elif sprint_id:
                sprint = await db.get(Sprint, uuid.UUID(sprint_id))
                if sprint:
                    project = await db.get(Project, sprint.project_id)
                    if project:
                        workspace_id = project.workspace_id
            elif task_id:
                task = await db.get(Task, uuid.UUID(task_id))
                if task:
                    project = await db.get(Project, task.project_id)
                    if project:
                        workspace_id = project.workspace_id
            elif epic_id:
                epic = await db.get(Epic, uuid.UUID(epic_id))
                if epic:
                    # workspace-level epics have no project
                    workspace_id = epic.workspace_id
            elif rule_id:
                rule = await db.get(AutomationRule, uuid.UUID(rule_id))
                if rule:
                    project = await db.get(Project, rule.project_id)
                    if project:
                        workspace_id = project.workspace_id

        if not workspace_id:
            # If we absolutely cannot resolve a workspace, we let it pass or fail?
            # Usually this means the entity doesn't exist, which will be caught by 404 later.
            return True

        workspace = await db.get(Workspace, workspace_id)
        if workspace:
            settings = workspace.settings or {}
            if not settings.get(feature_key, True):
                raise HTTPException(
                    status_code=403, detail=f"feature_disabled:{feature_key}"
                )
        return True

    return feature_checker
