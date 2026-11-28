import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_manager import BaseManager
from app.models.sprint import Sprint
from app.models.task import Task
from app.modules.sprints.schemas import SprintCreate, SprintUpdate


def _as_utc(value: datetime) -> datetime:
    """Treat naive datetimes as UTC so they can be compared with timestamptz columns."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class SprintManager(BaseManager[Sprint, SprintCreate, SprintUpdate]):
    async def get_sprints_by_project(
        self, db: AsyncSession, project_id: uuid.UUID
    ) -> list[Sprint]:
        query = (
            select(self.model)
            .where(
                self.model.project_id == project_id,
                self.model.is_deleted == False,
            )
            .order_by(
                self.model.start_date.asc().nulls_last(),
                self.model.started_at.asc().nulls_last(),
            )
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    # ──────────────────────────────────────────────────────────────────
    # Start sprint: planning → active
    # ──────────────────────────────────────────────────────────────────
    async def start_sprint(self, db: AsyncSession, sprint: Sprint) -> Sprint:
        """
        Start a sprint: status → active, started_at = now().
        Validate: a project can have only one active sprint at a time.
        """
        if sprint.status != "planning":
            raise HTTPException(
                status_code=400,
                detail="sprint.error_not_in_planning",
            )

        # Only one active sprint per project
        active_query = select(Sprint).where(
            Sprint.project_id == sprint.project_id,
            Sprint.status == "active",
            Sprint.id != sprint.id,
            Sprint.is_deleted == False,
        )
        existing_active = (await db.execute(active_query)).scalars().first()
        if existing_active:
            raise HTTPException(
                status_code=400,
                detail="sprint.error_already_active",
            )

        sprint.status = "active"
        sprint.started_at = datetime.now(UTC)
        await db.flush()
        await db.refresh(sprint)
        return sprint

    # ──────────────────────────────────────────────────────────────────
    # Complete sprint: active → completed
    # ──────────────────────────────────────────────────────────────────
    async def complete_sprint(
        self,
        db: AsyncSession,
        sprint: Sprint,
        incomplete_action: str,
        target_sprint_id: uuid.UUID | None,
    ) -> dict:
        """
        Complete a sprint:
        - incomplete_action = 'backlog'      → unfinished tasks → sprint_id = NULL
        - incomplete_action = 'next_sprint'  → unfinished tasks → sprint_id = target_sprint_id
        Returns summary stats for the frontend toast.
        """
        if sprint.status != "active":
            raise HTTPException(
                status_code=400,
                detail="sprint.error_not_active",
            )

        # All tasks of the sprint
        tasks_query = select(Task).where(
            Task.sprint_id == sprint.id,
            Task.is_deleted == False,
        )
        tasks = (await db.execute(tasks_query)).scalars().all()

        done_tasks = [t for t in tasks if t.status == "done"]
        incomplete_tasks = [t for t in tasks if t.status != "done"]

        # Freeze the scope before unfinished tasks leave the sprint
        sprint.completion_snapshot = {
            "tasks": [
                {
                    "id": str(t.id),
                    "hours": t.estimated_hours or 1.0,
                    "done": t.status == "done",
                    "done_at": _as_utc(t.updated_at).isoformat()
                    if t.status == "done" and t.updated_at
                    else None,
                }
                for t in tasks
            ]
        }

        if incomplete_action == "backlog":
            for task in incomplete_tasks:
                task.sprint_id = None

        elif incomplete_action == "next_sprint":
            if not target_sprint_id:
                raise HTTPException(
                    status_code=400,
                    detail="sprint.error_no_target_sprint",
                )
            target = await db.get(Sprint, target_sprint_id)
            if (
                not target
                or target.is_deleted
                or target.status == "completed"
                or target.id == sprint.id
                or target.project_id
                != sprint.project_id  # no moving tasks across projects
            ):
                raise HTTPException(
                    status_code=400,
                    detail="sprint.error_invalid_target_sprint",
                )
            for task in incomplete_tasks:
                task.sprint_id = target_sprint_id

        sprint.status = "completed"
        sprint.completed_at = datetime.now(UTC)
        await db.flush()

        return {
            "done_count": len(done_tasks),
            "incomplete_count": len(incomplete_tasks),
            "total_count": len(tasks),
        }

    # ──────────────────────────────────────────────────────────────────
    # Reopen sprint: completed → active
    # ──────────────────────────────────────────────────────────────────
    async def reopen_sprint(self, db: AsyncSession, sprint: Sprint) -> Sprint:
        """
        Reopen a completed sprint (e.g. completed by mistake).
        - Only allowed when no other sprint of the project is active.
        - Only the most recently started sprint can be reopened: once a later
          sprint has started, its tasks may have moved on and the older sprint
          could no longer hand its unfinished tasks to it.
        - Reset status = active, completed_at = None.
        - Tasks moved to the backlog / another sprint when it was completed
          do NOT come back automatically; users move them back if needed.
        """
        if sprint.status != "completed":
            raise HTTPException(
                status_code=400,
                detail="sprint.error_not_completed",
            )

        active_query = select(Sprint).where(
            Sprint.project_id == sprint.project_id,
            Sprint.status == "active",
            Sprint.is_deleted == False,
        )
        existing_active = (await db.execute(active_query)).scalars().first()
        if existing_active:
            raise HTTPException(
                status_code=400,
                detail="sprint.error_already_active",
            )

        newer_query = select(Sprint.id).where(
            Sprint.project_id == sprint.project_id,
            Sprint.id != sprint.id,
            Sprint.is_deleted == False,
            Sprint.status.in_(("active", "completed")),
            Sprint.started_at.isnot(None),
        )
        if sprint.started_at is not None:
            newer_query = newer_query.where(Sprint.started_at > sprint.started_at)
        if (await db.execute(newer_query.limit(1))).scalars().first():
            raise HTTPException(
                status_code=400,
                detail="sprint.error_newer_sprint_started",
            )

        sprint.status = "active"
        sprint.completed_at = None
        sprint.completion_snapshot = None
        await db.flush()
        await db.refresh(sprint)
        return sprint

    # ──────────────────────────────────────────────────────────────────
    # Sprint stats
    # ──────────────────────────────────────────────────────────────────
    async def _scope(self, db: AsyncSession, sprint: Sprint) -> list[dict]:
        """
        The tasks a sprint's report is about, as {hours, done, done_at}.
        A completed sprint uses the snapshot taken when it was completed; an
        open sprint (or one completed before snapshots existed) uses its
        current tasks, with updated_at as a proxy for when a task was done.
        """
        snapshot = sprint.completion_snapshot
        if sprint.status == "completed" and isinstance(snapshot, dict):
            return [
                {
                    "hours": float(item.get("hours") or 1.0),
                    "done": bool(item.get("done")),
                    "done_at": datetime.fromisoformat(item["done_at"])
                    if item.get("done_at")
                    else None,
                }
                for item in snapshot.get("tasks", [])
            ]

        tasks_query = select(Task).where(
            Task.sprint_id == sprint.id,
            Task.is_deleted == False,
        )
        tasks = (await db.execute(tasks_query)).scalars().all()
        return [
            {
                "hours": t.estimated_hours or 1.0,
                "done": t.status == "done",
                "done_at": _as_utc(t.updated_at)
                if t.status == "done" and t.updated_at is not None
                else None,
            }
            for t in tasks
        ]

    async def get_stats(self, db: AsyncSession, sprint: Sprint) -> dict:
        scope = await self._scope(db, sprint)

        total = len(scope)
        done = sum(1 for item in scope if item["done"])

        # Number of days the sprint actually ran
        actual_days = None
        if sprint.started_at:
            end_ts = sprint.completed_at or datetime.now(UTC)
            actual_days = max((_as_utc(end_ts) - _as_utc(sprint.started_at)).days, 1)

        return {
            "total_tasks": total,
            "done_tasks": done,
            "incomplete_tasks": total - done,
            "completion_rate": round(done / total * 100, 1) if total > 0 else 0.0,
            "velocity": done,
            "actual_days": actual_days,
        }

    # ──────────────────────────────────────────────────────────────────
    # Burndown chart data
    # ──────────────────────────────────────────────────────────────────
    async def get_burndown(self, db: AsyncSession, sprint: Sprint) -> list:
        """
        Daily data points for the burndown chart.

        - ideal_hours: the ideal line (linear decrease)
        - remaining_hours: the actual line (see _scope for when a task counts
          as done)

        Fallback: tasks without estimated_hours count as 1 unit each.
        """
        scope = await self._scope(db, sprint)

        if not scope:
            return []

        # Start: prefer started_at (actual) over start_date (planned)
        start: datetime | None = sprint.started_at
        if not start and sprint.start_date:
            start = datetime.combine(sprint.start_date, datetime.min.time())
        if not start:
            return []

        # End: completed_at, else end_date, else today
        end: datetime | None = sprint.completed_at
        if not end and sprint.end_date:
            end = datetime.combine(sprint.end_date, datetime.min.time())
        if not end:
            end = datetime.now(UTC)

        start, end = _as_utc(start), _as_utc(end)
        total_hours = sum(item["hours"] for item in scope)
        # bounded: dates are validated, but never loop over years of days
        total_days = min(max((end - start).days, 1), 366)

        points = []
        for day_offset in range(total_days + 1):
            current_day = start + timedelta(days=day_offset)
            # the last point is the end itself, so work finished on the last
            # (partial) day still burns down
            if day_offset == total_days and end > current_day:
                current_day = end

            # Ideal line: decreases evenly from total to 0
            ideal = total_hours * (1 - day_offset / total_days)

            # Actual line: hours of tasks NOT done by that day
            remaining = sum(
                item["hours"]
                for item in scope
                if not (
                    item["done"]
                    and item["done_at"] is not None
                    and _as_utc(item["done_at"]) <= current_day
                )
            )

            points.append(
                {
                    "date": current_day.strftime("%d/%m"),
                    "ideal_hours": round(ideal, 1),
                    "remaining_hours": round(remaining, 1),
                }
            )

        return points


sprint_manager = SprintManager(Sprint)
