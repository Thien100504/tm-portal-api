"""
Automation Rules Router

Project-scoped:
  GET    /api/v1/projects/{project_id}/automations/      list rules
  POST   /api/v1/projects/{project_id}/automations/      create rule

Rule-scoped (detail_router):
  GET    /api/v1/automations/{rule_id}                   get rule
  PUT    /api/v1/automations/{rule_id}                   update rule
  DELETE /api/v1/automations/{rule_id}                   delete rule
  PATCH  /api/v1/automations/{rule_id}/toggle            toggle active
"""

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.automation import AutomationRule
from app.modules.auth.dependencies import get_current_active_user
from app.modules.projects.dependencies import get_project_access, get_project_pm_access
from app.modules.automation.manager import automation_manager
from app.modules.automation.schemas import (
    AutomationRuleCreate,
    AutomationRuleResponse,
    AutomationRuleUpdate,
)

router = APIRouter(tags=["automation"])


# ── Project-scoped ────────────────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/automations", response_model=List[AutomationRuleResponse]
)
async def list_rules(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List the automation rules of the project."""
    await get_project_access(project_id, db, current_user)
    return await automation_manager.list_by_project(db, project_id)


@router.post(
    "/projects/{project_id}/automations",
    response_model=AutomationRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_rule(
    project_id: uuid.UUID,
    rule_in: AutomationRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Create an automation rule. PM/owner only."""
    await get_project_pm_access(project_id, db, current_user)
    rule = await automation_manager.create(db, project_id, rule_in, current_user.id)
    await db.commit()
    return rule


# ── Rule-detail ───────────────────────────────────────────────────────────────


@router.get("/automations/{rule_id}", response_model=AutomationRuleResponse)
async def get_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    rule = await _get_or_404(db, rule_id)
    await get_project_access(rule.project_id, db, current_user)
    return rule


@router.put("/automations/{rule_id}", response_model=AutomationRuleResponse)
async def update_rule(
    rule_id: uuid.UUID,
    rule_in: AutomationRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Update a rule. PM/owner only."""
    rule = await _get_or_404(db, rule_id)
    await get_project_pm_access(rule.project_id, db, current_user)
    rule = await automation_manager.update(db, rule, rule_in)
    await db.commit()
    return rule


@router.delete("/automations/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Delete a rule. PM/owner only."""
    rule = await _get_or_404(db, rule_id)
    await get_project_pm_access(rule.project_id, db, current_user)
    await automation_manager.delete(db, rule)
    await db.commit()


@router.patch("/automations/{rule_id}/toggle", response_model=AutomationRuleResponse)
async def toggle_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Enable/disable a rule. PM/owner only."""
    rule = await _get_or_404(db, rule_id)
    await get_project_pm_access(rule.project_id, db, current_user)
    rule = await automation_manager.toggle(db, rule)
    await db.commit()
    return rule


# ── Helper ────────────────────────────────────────────────────────────────────


async def _get_or_404(db: AsyncSession, rule_id: uuid.UUID) -> "AutomationRule":
    rule = await automation_manager.get(db, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="automation.not_found")
    return rule
