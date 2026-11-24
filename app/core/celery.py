"""
Celery Core Configuration
"""

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "task_manager",
    broker=settings.RABBITMQ_URL,
    backend=settings.REDIS_URL,
    include=["app.workers.cron_tasks"],
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
        "task": "app.workers.cron_tasks.check_overdue_tasks",
        "schedule": 30.0 * 60,  # every 30 minutes (in seconds)
        "options": {"queue": "default"},
    },
    "snapshot_sprint_progress": {
        "task": "app.workers.cron_tasks.snapshot_sprint_progress",
        "schedule": crontab(hour=0, minute=0),  # daily at midnight
        "options": {"queue": "default"},
    },
}
