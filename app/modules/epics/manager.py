import uuid
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_manager import BaseManager
from app.models.epic import Epic
from app.modules.epics.schemas import EpicCreate, EpicUpdate


class EpicManager(BaseManager[Epic, EpicCreate, EpicUpdate]):
    async def get_epics_by_workspace(
        self, db: AsyncSession, workspace_id: uuid.UUID
    ) -> list[Epic]:
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
    ) -> list[Epic]:
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

    async def soft_delete(
        self, db: AsyncSession, epic: Epic, user_id: uuid.UUID
    ) -> None:
        """Mark the epic deleted; tasks keep their epic_id for history."""
        from datetime import datetime

        epic.is_deleted = True
        epic.deleted_at = datetime.now(UTC)
        epic.deleted_by = user_id
        await db.flush()


epic_manager = EpicManager(Epic)
