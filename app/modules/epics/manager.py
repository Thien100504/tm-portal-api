import uuid
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_manager import BaseManager
from app.models.epic import Epic
from app.modules.epics.schemas import EpicCreate, EpicUpdate


class EpicManager(BaseManager[Epic, EpicCreate, EpicUpdate]):
    async def get_epics_by_workspace(
        self, db: AsyncSession, workspace_id: uuid.UUID
    ) -> List[Epic]:
        query = (
            select(self.model)
            .where(
                self.model.workspace_id == workspace_id,
                self.model.is_deleted == False,
            )
            .order_by(self.model.created_at.desc())
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_epics_by_project(
        self, db: AsyncSession, project_id: uuid.UUID
    ) -> List[Epic]:
        query = (
            select(self.model)
            .where(
                self.model.project_id == project_id,
                self.model.is_deleted == False,
            )
            .order_by(self.model.created_at.desc())
        )
        result = await db.execute(query)
        return list(result.scalars().all())


epic_manager = EpicManager(Epic)
