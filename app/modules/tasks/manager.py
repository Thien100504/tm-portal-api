import uuid
import asyncio
import logging
from typing import List, Optional, Any, Dict, Union

from fastapi import HTTPException
from sqlalchemy import func, select, update as sa_update, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, noload

logger = logging.getLogger(__name__)

from app.core.base_manager import BaseManager
from app.models.task import Task, TaskDependency, Comment
from app.models.project import ProjectMember
from app.modules.tasks.schemas import TaskCreate, TaskUpdate


class TaskManager(BaseManager[Task, TaskCreate, TaskUpdate]):
    async def get_by_id(self, db: AsyncSession, task_id: uuid.UUID) -> Optional[Task]:
        """
        Task details: loads subtasks, dependencies and dependent_tasks.
        Used by TaskDetailModal.
        """
        query = (
            select(Task)
            .options(
                selectinload(Task.subtasks),
                selectinload(Task.dependencies),
                selectinload(Task.dependent_tasks),
            )
            .where(Task.id == task_id, Task.is_deleted.is_(False))
        )
        result = await db.execute(query)
        task = result.scalars().first()
        if task:
            # Post-filter: drop soft-deleted subtasks
            # selectinload does not filter is_deleted on relationships
            task.subtasks = [s for s in task.subtasks if not s.is_deleted]
        return task

    async def get_tasks_by_project(
        self, db: AsyncSession, project_id: uuid.UUID
    ) -> List[Task]:
        """
        Tasks for the Kanban board.
        Only loads subtasks (needed for the progress bar), NOT dependencies,
        since the board does not show them (avoids 2 needless queries).
        """
        query = (
            select(Task)
            .options(
                selectinload(Task.subtasks),
                noload(Task.dependencies),
                noload(Task.dependent_tasks),
            )
            .where(Task.project_id == project_id, Task.is_deleted.is_(False))
            .order_by(Task.position.asc().nulls_last(), Task.created_at.desc())
        )
        result = await db.execute(query)
        tasks = list(result.scalars().all())

        # Post-filter: drop soft-deleted subtasks from the nested array
        # e.g. an AI breakdown soft-deletes old subtasks; they must not count in the progress bar
        for task in tasks:
            task.subtasks = [s for s in task.subtasks if not s.is_deleted]

        return tasks

    async def create_task(
        self, db: AsyncSession, obj_in: TaskCreate, creator_id: uuid.UUID
    ) -> Task:
        max_pos_query = select(func.max(Task.position)).where(
            Task.project_id == obj_in.project_id, Task.status == "todo"
        )
        max_pos_result = await db.execute(max_pos_query)
        max_pos = max_pos_result.scalar() or 0

        if obj_in.parent_task_id:
            parent_task = await db.get(Task, obj_in.parent_task_id)
            if not parent_task:
                raise HTTPException(status_code=404, detail="task.parent_not_found")
            if parent_task.parent_task_id:
                raise HTTPException(status_code=400, detail="task.subtask_depth_limit")

        from app.models.project import Project

        project = await db.get(Project, obj_in.project_id)
        workspace_id = project.workspace_id if project else None

        task = Task(
            **obj_in.model_dump(),
            workspace_id=workspace_id,
            created_by=creator_id,
            position=max_pos + 1,
        )

        # Check subtask deadline against parent
        if task.parent_task_id and task.deadline:
            parent_task = await db.get(Task, task.parent_task_id)
            if (
                parent_task
                and parent_task.deadline
                and task.deadline > parent_task.deadline
            ):
                raise HTTPException(
                    status_code=400, detail="task.error_subtask_deadline"
                )

        db.add(task)
        await db.flush()
        return task

    async def update(
        self,
        db: AsyncSession,
        *,
        db_obj: Task,
        obj_in: Union[TaskUpdate, Dict[str, Any]],
    ) -> Task:
        # The new deadline if it is being updated
        new_deadline = None
        if isinstance(obj_in, dict):
            new_deadline = obj_in.get("deadline", db_obj.deadline)
        else:
            update_data = obj_in.model_dump(exclude_unset=True)
            new_deadline = update_data.get("deadline", db_obj.deadline)

        # 1. Rule: a subtask's deadline cannot be later than its parent's
        if db_obj.parent_task_id and new_deadline:
            parent_task = await db.get(Task, db_obj.parent_task_id)
            if (
                parent_task
                and parent_task.deadline
                and new_deadline > parent_task.deadline
            ):
                raise HTTPException(
                    status_code=400,
                    detail="task.error_subtask_deadline_later_than_parent",
                )

        # 2. Rule: a parent's deadline cannot be earlier than any subtask's
        if new_deadline:
            subtasks_query = select(Task.deadline).where(
                Task.parent_task_id == db_obj.id, Task.deadline.isnot(None)
            )
            subtasks_res = await db.execute(subtasks_query)
            for st_deadline in subtasks_res.scalars():
                if new_deadline < st_deadline:
                    raise HTTPException(
                        status_code=400,
                        detail="task.error_parent_deadline_earlier_than_subtask",
                    )

        # ── Cascade sprint_id & epic_id → subtasks ──────────────────────────────
        # When a parent moves to another sprint/epic, its subtasks follow.
        _UNCHANGED = object()
        new_sprint_id = _UNCHANGED
        new_epic_id = _UNCHANGED
        if isinstance(obj_in, dict):
            if "sprint_id" in obj_in:
                new_sprint_id = obj_in["sprint_id"]
            if "epic_id" in obj_in:
                new_epic_id = obj_in["epic_id"]
        else:
            _dump = obj_in.model_dump(exclude_unset=True)
            if "sprint_id" in _dump:
                new_sprint_id = _dump["sprint_id"]
            if "epic_id" in _dump:
                new_epic_id = _dump["epic_id"]

        if new_sprint_id is not _UNCHANGED and new_sprint_id != db_obj.sprint_id:
            await db.execute(
                sa_update(Task)
                .where(Task.parent_task_id == db_obj.id, Task.is_deleted.is_(False))
                .values(sprint_id=new_sprint_id)
            )

        if new_epic_id is not _UNCHANGED and new_epic_id != db_obj.epic_id:
            await db.execute(
                sa_update(Task)
                .where(Task.parent_task_id == db_obj.id, Task.is_deleted.is_(False))
                .values(epic_id=new_epic_id)
            )

        return await super().update(db, db_obj=db_obj, obj_in=obj_in)

    async def update_status(
        self, db: AsyncSession, task: Task, new_status: str, override: bool = False
    ) -> Task:
        if new_status == "done":
            subtasks_query = select(Task).where(
                Task.parent_task_id == task.id, Task.status != "done"
            )
            subtasks = (await db.execute(subtasks_query)).scalars().all()
            if subtasks:
                raise HTTPException(
                    status_code=400, detail="task.error_subtasks_not_done"
                )
        elif new_status == "in_progress" and not override:
            deps_query = (
                select(Task)
                .join(TaskDependency, Task.id == TaskDependency.depends_on_id)
                .where(TaskDependency.task_id == task.id, Task.status != "done")
            )
            unfinished_deps = (await db.execute(deps_query)).scalars().all()
            if unfinished_deps:
                raise HTTPException(
                    status_code=400, detail="task.error_dependencies_not_done"
                )

        # Moving the parent moves the children (cascade status to subtasks)
        if new_status in ["in_progress", "review"]:
            subtasks_query = select(Task).where(Task.parent_task_id == task.id)
            subtasks = (await db.execute(subtasks_query)).scalars().all()
            for sub in subtasks:
                if new_status == "in_progress" and sub.status == "todo":
                    sub.status = "in_progress"
                elif new_status == "review" and sub.status in ["todo", "in_progress"]:
                    sub.status = "review"

        task.status = new_status
        return task

    async def update_position(
        self,
        db: AsyncSession,
        task: Task,
        new_status: str,
        insert_after_id: Optional[uuid.UUID] = None,
    ) -> Task:
        # When the column changes, update the status and cascade
        if task.status != new_status:
            await self.update_status(db, task, new_status, override=True)

        # Reorder positions
        tasks_in_col_query = (
            select(Task)
            .where(
                Task.project_id == task.project_id,
                Task.status == new_status,
                Task.parent_task_id.is_(None),
            )
            .order_by(Task.position.asc().nulls_last(), Task.created_at.desc())
        )

        tasks_in_col = list((await db.execute(tasks_in_col_query)).scalars().all())

        if task in tasks_in_col:
            tasks_in_col.remove(task)

        insert_idx = 0
        if insert_after_id:
            for i, t in enumerate(tasks_in_col):
                if t.id == insert_after_id:
                    insert_idx = i + 1
                    break

        tasks_in_col.insert(insert_idx, task)

        # Renumber the positions
        for idx, t in enumerate(tasks_in_col):
            t.position = idx + 1

        return task

    async def check_circular_dependency(
        self, db: AsyncSession, task_id: uuid.UUID, depends_on_id: uuid.UUID
    ) -> bool:
        """
        Check if adding a dependency: task_id -> depends_on_id
        would create a cycle. Optimized using PostgreSQL Recursive CTE
        to avoid N+1 query problem.
        """
        query = text("""
            WITH RECURSIVE deps AS (
                SELECT depends_on_id FROM task_dependencies WHERE task_id = :start_id
                UNION
                SELECT td.depends_on_id 
                FROM task_dependencies td
                INNER JOIN deps d ON d.depends_on_id = td.task_id
            )
            SELECT 1 FROM deps WHERE depends_on_id = :target_id LIMIT 1;
        """)

        try:
            res = await db.execute(
                query, {"start_id": str(depends_on_id), "target_id": str(task_id)}
            )
            return res.scalar() is not None
        except (OperationalError, asyncio.TimeoutError):
            logger.exception("DB Timeout or Error in check_circular_dependency")
            raise HTTPException(status_code=503, detail="server.db_unavailable")

    async def check_and_unblock_dependents(
        self, db: AsyncSession, completed_task_id: uuid.UUID
    ) -> List[Task]:
        """
        Scan the tasks that depend on the task that was just completed.
        Those no longer blocked by any other task
        are returned so that an unblocked event can be emitted.
        """
        dependent_query = (
            select(Task)
            .join(TaskDependency, Task.id == TaskDependency.task_id)
            .where(TaskDependency.depends_on_id == completed_task_id)
            .where(Task.status != "done")
        )
        dependent_tasks = (await db.execute(dependent_query)).scalars().all()

        unblocked_tasks = []
        for d_task in dependent_tasks:
            unfinished_deps_query = (
                select(Task.id)
                .join(TaskDependency, Task.id == TaskDependency.depends_on_id)
                .where(TaskDependency.task_id == d_task.id)
                .where(Task.status != "done")
                .limit(1)
            )
            is_blocked = (await db.execute(unfinished_deps_query)).scalar()
            if not is_blocked:
                unblocked_tasks.append(d_task)

        return unblocked_tasks

    async def get_impacted_descendants(
        self, db: AsyncSession, task_id: uuid.UUID
    ) -> List[Task]:
        query = text("""
            WITH RECURSIVE deps AS (
                SELECT task_id FROM task_dependencies WHERE depends_on_id = :start_id
                UNION
                SELECT td.task_id 
                FROM task_dependencies td
                INNER JOIN deps d ON d.task_id = td.depends_on_id
            )
            SELECT task_id FROM deps;
        """)
        try:
            res = await db.execute(query, {"start_id": str(task_id)})
            descendant_ids = [row[0] for row in res.all()]
        except (OperationalError, asyncio.TimeoutError):
            logger.exception("DB Timeout or Error in get_impacted_descendants")
            return []
        if not descendant_ids:
            return []

        tasks_query = select(Task).where(
            Task.id.in_(descendant_ids),
            Task.status != "done",
            Task.deadline.isnot(None),
        )
        tasks = (await db.execute(tasks_query)).scalars().all()
        return list(tasks)

    async def cascade_deadlines(
        self, db: AsyncSession, task_id: uuid.UUID, delta_days: int
    ) -> int:
        descendants = await self.get_impacted_descendants(db, task_id)
        if not descendants:
            return 0

        from datetime import timedelta

        count = 0
        for task in descendants:
            if task.deadline:
                task.deadline = task.deadline + timedelta(days=delta_days)
                count += 1
        return count

    async def add_dependency(
        self, db: AsyncSession, task: Task, depends_on_id: uuid.UUID
    ) -> TaskDependency:
        if task.id == depends_on_id:
            raise HTTPException(status_code=400, detail="task.error_self_dependency")
        is_circular = await self.check_circular_dependency(db, task.id, depends_on_id)
        if is_circular:
            raise HTTPException(
                status_code=400, detail="task.error_circular_dependency"
            )
        dep = TaskDependency(task_id=task.id, depends_on_id=depends_on_id)
        db.add(dep)
        return dep

    async def remove_dependency(
        self, db: AsyncSession, task: Task, depends_on_id: uuid.UUID
    ) -> None:
        query = select(TaskDependency).where(
            TaskDependency.task_id == task.id,
            TaskDependency.depends_on_id == depends_on_id,
        )
        dep = (await db.execute(query)).scalars().first()
        if dep:
            await db.delete(dep)

    async def assign_task(
        self, db: AsyncSession, task: Task, assignee_id: uuid.UUID
    ) -> Task:
        member_query = select(ProjectMember).where(
            ProjectMember.project_id == task.project_id,
            ProjectMember.user_id == assignee_id,
            ProjectMember.is_deleted.is_(False),
        )
        is_member = (await db.execute(member_query)).scalars().first()
        if not is_member:
            raise HTTPException(
                status_code=400, detail="task.error_assignee_not_member"
            )
        task.assignee_id = assignee_id
        return task

    async def add_comment(
        self, db: AsyncSession, task_id: uuid.UUID, user_id: uuid.UUID, content: str
    ) -> Comment:
        comment = Comment(task_id=task_id, user_id=user_id, content=content)
        db.add(comment)
        await db.flush()
        return comment

    async def get_comments(self, db: AsyncSession, task_id: uuid.UUID) -> List[Comment]:
        query = (
            select(Comment)
            .where(Comment.task_id == task_id)
            .order_by(Comment.created_at.asc())
        )
        result = await db.execute(query)
        return list(result.scalars().all())


task_manager = TaskManager(Task)
