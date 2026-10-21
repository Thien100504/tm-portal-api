import uuid
import logging
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.events.publisher import EventPublisher
from app.events.task_events import task_events
from app.models.user import User
from app.modules.auth.dependencies import get_current_active_user
from app.modules.projects.manager import project_manager
from app.modules.projects.dependencies import get_project_access
from app.modules.tasks import schemas
from app.modules.tasks.manager import task_manager
from app.modules.automation.manager import automation_manager

router = APIRouter(prefix="/tasks", tags=["tasks"])
logger = logging.getLogger(__name__)


# ── Helper for AI events (simple RabbitMQ publish) ───────────────────
def _publish_rabbitmq(routing_key: str, payload: dict):
    try:
        with EventPublisher() as pub:
            pub.publish(routing_key, payload)
    except Exception:
        logger.exception("Failed to publish %s", routing_key)


# ═════════════════════════════════════════════════════════════════════
# CRUD
# ═════════════════════════════════════════════════════════════════════


@router.post(
    "", response_model=schemas.TaskResponseBase, status_code=status.HTTP_201_CREATED
)
async def create_task(
    task_in: schemas.TaskCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    await get_project_access(task_in.project_id, db, current_user)

    task = await task_manager.create_task(
        db, obj_in=task_in, creator_id=current_user.id
    )
    await db.flush()
    await db.refresh(task)

    await automation_manager.execute_rules(db, task.project_id, "task.created", task)
    await db.commit()
    await db.refresh(task)

    extra = {}
    if task.assignee_id and task.assignee_id != current_user.id:
        assignee = await db.get(User, task.assignee_id)
        if assignee:
            extra["message"] = (
                f"Created by {current_user.full_name} · Assigned to {assignee.full_name}"
            )

    await task_events.emit(
        db, background_tasks, "task.created", task, actor=current_user, extra=extra
    )
    return task


@router.get("/my-day", response_model=List[schemas.TaskResponse])
async def get_my_day_tasks(
    workspace_id: Optional[uuid.UUID] = Query(None, description="Filter by workspace"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    from datetime import date
    from sqlalchemy import select, and_, func
    from sqlalchemy.orm import selectinload, noload
    from app.models.task import Task
    from app.models.project import Project

    today = date.today()
    stmt = select(Task).options(
        selectinload(Task.subtasks),
        noload(Task.dependencies),
        noload(Task.dependent_tasks),
    )
    if workspace_id:
        stmt = stmt.join(Project, Task.project_id == Project.id).where(
            Project.workspace_id == workspace_id
        )

    stmt = stmt.where(
        and_(
            Task.assignee_id == current_user.id,
            func.date(Task.deadline) == today,
            Task.is_deleted == False,
        )
    )
    stmt = stmt.order_by(Task.priority.desc(), Task.created_at.asc())
    result = await db.execute(stmt)
    tasks = list(result.scalars().all())
    for task in tasks:
        task.subtasks = [s for s in task.subtasks if not s.is_deleted]
    return tasks


@router.get("", response_model=List[schemas.TaskResponse])
async def get_tasks(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    await get_project_access(project_id, db, current_user)
    return await task_manager.get_tasks_by_project(db, project_id)


@router.get("/{task_id}", response_model=schemas.TaskResponse)
async def get_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    task = await task_manager.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task.not_found")
    await get_project_access(task.project_id, db, current_user)
    return task


@router.put("/{task_id}", response_model=schemas.TaskResponseBase)
async def update_task(
    task_id: uuid.UUID,
    task_in: schemas.TaskUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    task = await task_manager.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task.not_found")
    await get_project_access(task.project_id, db, current_user)

    old_priority = task.priority
    task = await task_manager.update(db, db_obj=task, obj_in=task_in)

    if task_in.priority is not None and task_in.priority != old_priority:
        await automation_manager.execute_rules(
            db,
            task.project_id,
            "task.priority_changed",
            task,
            context={"old_priority": old_priority, "new_priority": task.priority},
        )

    await db.commit()

    await task_events.emit(
        db,
        background_tasks,
        "task.updated",
        task,
        actor=current_user,
        extra={"changes": task_in.model_dump(exclude_unset=True)},
    )
    await db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    task = await task_manager.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task.not_found")
    await get_project_access(task.project_id, db, current_user)

    from datetime import datetime
    from sqlalchemy import update as sa_update
    from app.models.task import Task

    now = datetime.utcnow()
    task.is_deleted = True
    task.deleted_at = now
    task.deleted_by = current_user.id

    # Cascade soft-delete to subtasks
    await db.execute(
        sa_update(Task)
        .where(Task.parent_task_id == task_id, Task.is_deleted == False)
        .values(is_deleted=True, deleted_at=now, deleted_by=current_user.id)
    )

    await db.flush()
    await db.commit()

    await task_events.emit(
        db, background_tasks, "task.deleted", task, actor=current_user
    )


# ═════════════════════════════════════════════════════════════════════
# Status / Position / Assign
# ═════════════════════════════════════════════════════════════════════


@router.put("/{task_id}/status", response_model=schemas.TaskResponseBase)
async def update_task_status(
    task_id: uuid.UUID,
    status_in: schemas.TaskStatusUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    task = await task_manager.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task.not_found")

    member = await project_manager.get_member(db, task.project_id, current_user.id)
    if not member and current_user.system_role != "admin":
        raise HTTPException(status_code=403, detail="auth.not_permitted")
    is_pm = member and member.project_role == "project_manager"
    if status_in.override and not is_pm and current_user.system_role != "admin":
        raise HTTPException(status_code=403, detail="auth.only_pm_override")

    old_status = task.status
    task = await task_manager.update_status(
        db, task, status_in.status, override=status_in.override
    )
    await db.flush()
    await db.refresh(task)

    await automation_manager.execute_rules(
        db,
        task.project_id,
        "task.status_changed",
        task,
        context={"old_status": old_status, "new_status": task.status},
    )
    await db.commit()

    await task_events.emit(
        db,
        background_tasks,
        "task.updated",
        task,
        actor=current_user,
        extra={
            "changes": {"status": task.status, "old_status": old_status},
            "title": f"🔄 {task.title[:60]}",
            "message": f"Moved {old_status} → {task.status} by {current_user.full_name}",
        },
    )

    if task.status == "done":
        await task_events.emit(
            db, background_tasks, "task.completed", task, actor=current_user
        )

        if task.created_by and task.created_by != current_user.id:
            await task_events.emit_direct_notification(
                db,
                user_id=task.created_by,
                title_key="notification.task.completed",
                title_params={"title": task.title[:60]},
                message_key="notification.task.completed_by",
                message_params={"actor": current_user.full_name},
                type="success",
                entity_id=task.id,
                project_id=task.project_id,
            )
            await db.commit()

        unblocked_tasks = await task_manager.check_and_unblock_dependents(db, task.id)
        for u_task in unblocked_tasks:
            if u_task.assignee_id:
                await task_events.emit_direct_notification(
                    db,
                    user_id=u_task.assignee_id,
                    title_key="notification.task.unblocked",
                    title_params={"title": u_task.title[:60]},
                    message_key="notification.task.unblocked_message",
                    message_params={},
                    type="info",
                    entity_id=u_task.id,
                    project_id=u_task.project_id,
                )
            await task_events.emit(
                db, background_tasks, "task.unblocked", u_task, actor=current_user
            )
        if unblocked_tasks:
            await db.commit()

    await db.refresh(task)
    return task


@router.put("/{task_id}/position", response_model=schemas.TaskResponseBase)
async def update_task_position(
    task_id: uuid.UUID,
    position_in: schemas.TaskPositionUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    task = await task_manager.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task.not_found")
    await get_project_access(task.project_id, db, current_user)

    task = await task_manager.update_position(
        db,
        task,
        new_status=position_in.status,
        insert_after_id=position_in.insert_after_id,
    )
    await db.flush()
    await db.refresh(task)
    await db.commit()

    await task_events.emit(
        db,
        background_tasks,
        "task.updated",
        task,
        actor=current_user,
        extra={"changes": {"position": "Updated", "status": position_in.status}},
    )
    return task


@router.put("/{task_id}/assign", response_model=schemas.TaskResponseBase)
async def assign_task(
    task_id: uuid.UUID,
    assign_in: schemas.TaskAssign,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    task = await task_manager.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task.not_found")

    if assign_in.assignee_id:
        task = await task_manager.assign_task(db, task, assign_in.assignee_id)
        await automation_manager.execute_rules(
            db, task.project_id, "task.assigned", task
        )
    else:
        task.assignee_id = None

    await db.flush()
    await db.refresh(task)
    await db.commit()

    if task.assignee_id:
        await task_events.emit(
            db,
            background_tasks,
            "task.assigned",
            task,
            actor=current_user,
            extra={"assignee_id": str(task.assignee_id)},
        )

        if task.assignee_id != current_user.id:
            await task_events.emit_direct_notification(
                db,
                user_id=task.assignee_id,
                title_key="notification.task.assigned",
                title_params={"title": task.title[:60]},
                message_key="notification.task.assigned_by",
                message_params={"actor": current_user.full_name},
                type="assignment",
                entity_id=task.id,
                project_id=task.project_id,
            )
            await db.commit()
    else:
        await task_events.emit(
            db, background_tasks, "task.updated", task, actor=current_user
        )

    await db.refresh(task)
    return task


# ═════════════════════════════════════════════════════════════════════
# Comments
# ═════════════════════════════════════════════════════════════════════


@router.post("/{task_id}/comments", response_model=schemas.CommentResponse)
async def add_comment(
    task_id: uuid.UUID,
    comment_in: schemas.CommentCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    task = await task_manager.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task.not_found")
    await get_project_access(task.project_id, db, current_user)

    comment = await task_manager.add_comment(
        db, task_id=task_id, user_id=current_user.id, content=comment_in.content
    )
    await db.flush()
    await db.refresh(comment)
    await db.commit()

    await task_events.emit(
        db,
        background_tasks,
        "task.commented",
        task,
        actor=current_user,
        extra={
            "comment_id": str(comment.id),
            "content": comment.content,
            "message": f"{task.title[:60]}: {comment.content[:100]}",
        },
    )
    return comment


@router.get("/{task_id}/comments", response_model=List[schemas.CommentResponse])
async def get_comments(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    task = await task_manager.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task.not_found")
    await get_project_access(task.project_id, db, current_user)
    return await task_manager.get_comments(db, task_id=task_id)


# ═════════════════════════════════════════════════════════════════════
# Dependencies
# ═════════════════════════════════════════════════════════════════════


@router.post("/{task_id}/dependencies", response_model=schemas.TaskDependencyResponse)
async def add_dependency(
    task_id: uuid.UUID,
    dep_in: schemas.TaskDependencyCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    task = await task_manager.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task.not_found")
    await get_project_access(task.project_id, db, current_user)

    dep = await task_manager.add_dependency(
        db, task=task, depends_on_id=dep_in.depends_on_id
    )
    await db.flush()
    await db.commit()

    await task_events.emit(
        db, background_tasks, "task.updated", task, actor=current_user
    )
    await db.refresh(dep)
    return dep


@router.delete(
    "/{task_id}/dependencies/{depends_on_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_dependency(
    task_id: uuid.UUID,
    depends_on_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    task = await task_manager.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task.not_found")
    await get_project_access(task.project_id, db, current_user)

    await task_manager.remove_dependency(db, task=task, depends_on_id=depends_on_id)
    await db.flush()
    await db.commit()

    await task_events.emit(
        db, background_tasks, "task.updated", task, actor=current_user
    )


# ═════════════════════════════════════════════════════════════════════
# AI
# ═════════════════════════════════════════════════════════════════════


@router.post("/{task_id}/ai/breakdown", status_code=status.HTTP_202_ACCEPTED)
async def request_ai_breakdown(
    task_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    task = await task_manager.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task.not_found")
    await get_project_access(task.project_id, db, current_user)

    background_tasks.add_task(
        _publish_rabbitmq,
        "task.ai.breakdown",
        {
            "task_id": str(task.id),
            "title": task.title,
            "description": task.description or "",
            "project_id": str(task.project_id),
            "actor_id": str(current_user.id),
        },
    )
    return {"status": "accepted", "message": "AI is breaking down the task"}


@router.post("/{task_id}/ai/estimate", status_code=status.HTTP_202_ACCEPTED)
async def request_ai_estimate(
    task_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    task = await task_manager.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task.not_found")
    await get_project_access(task.project_id, db, current_user)

    background_tasks.add_task(
        _publish_rabbitmq,
        "task.ai.estimate",
        {
            "task_id": str(task.id),
            "title": task.title,
            "description": task.description or "",
            "project_id": str(task.project_id),
            "actor_id": str(current_user.id),
        },
    )
    return {"status": "accepted", "message": "AI is estimating the task"}


# ═════════════════════════════════════════════════════════════════════
# Cascade Deadline
# ═════════════════════════════════════════════════════════════════════


@router.get(
    "/{task_id}/impacted-dependencies",
    response_model=List[schemas.ImpactedTaskResponse],
)
async def get_impacted_dependencies(
    task_id: uuid.UUID,
    delta_days: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    task = await task_manager.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task.not_found")
    await get_project_access(task.project_id, db, current_user)

    descendants = await task_manager.get_impacted_descendants(db, task_id)
    from datetime import timedelta

    return [
        {
            "id": d.id,
            "title": d.title,
            "current_deadline": d.deadline,
            "new_deadline": (d.deadline + timedelta(days=delta_days))
            if d.deadline
            else None,
        }
        for d in descendants
    ]


@router.post("/{task_id}/cascade-deadline", status_code=status.HTTP_200_OK)
async def apply_cascade_deadline(
    task_id: uuid.UUID,
    request: schemas.CascadeDeadlineRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    task = await task_manager.get_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task.not_found")
    await get_project_access(task.project_id, db, current_user)

    count = await task_manager.cascade_deadlines(db, task_id, request.delta_days)
    if count > 0:
        await db.commit()
        await task_events.emit(
            db, background_tasks, "task.updated", task, actor=current_user
        )

    return {"status": "ok", "updated_count": count}
