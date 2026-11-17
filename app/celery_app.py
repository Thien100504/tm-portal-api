"""
Celery application with a Beat schedule (GAP-06 fix).

Broker: RabbitMQ
Backend: Redis
Beat schedule:
  - check_overdue_tasks: every 30 minutes
  - snapshot_sprint_progress: daily at 00:00
"""

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "task_manager",
    broker=settings.RABBITMQ_URL,
    backend=settings.REDIS_URL,
)

# ── General settings ─────────────────────────────────────────────────
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Ho_Chi_Minh",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# ── Beat Schedule (GAP-06 fix) ───────────────────────────────────────
celery_app.conf.beat_schedule = {
    "check_overdue_tasks": {
        "task": "app.celery_app.check_overdue_tasks",
        "schedule": 30.0 * 60,  # every 30 minutes (in seconds)
        "options": {"queue": "default"},
    },
    "snapshot_sprint_progress": {
        "task": "app.celery_app.snapshot_sprint_progress",
        "schedule": crontab(hour=0, minute=0),  # daily at midnight
        "options": {"queue": "default"},
    },
}


# ── Task Stubs ────────────────────────────────────────────────────────


@celery_app.task(bind=True, name="app.celery_app.check_overdue_tasks")
def check_overdue_tasks(self) -> dict[str, str]:
    """
    Check and update overdue tasks.

    Runs every 30 minutes via Celery Beat.
    TODO: implement the deadline check and the notifications.
    """
    # Placeholder - to be implemented later
    return {"status": "completed", "message": "Checked overdue tasks"}


@celery_app.task(bind=True, name="app.celery_app.snapshot_sprint_progress")
def snapshot_sprint_progress(self) -> dict[str, str]:
    """
    Take a daily snapshot of sprint progress.

    Runs daily at 00:00 via Celery Beat.
    TODO: compute and store the burndown chart snapshot.
    """
    # Placeholder - to be implemented later
    return {"status": "completed", "message": "Sprint progress snapshot saved"}
