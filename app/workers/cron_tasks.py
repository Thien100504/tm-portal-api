"""
Celery Scheduled Tasks (Cron Jobs)
"""

from app.core.celery import celery_app


@celery_app.task(bind=True, name="app.workers.cron_tasks.check_overdue_tasks")
def check_overdue_tasks(self) -> dict[str, str]:
    """
    Check and update overdue tasks.

    Runs every 30 minutes via Celery Beat.
    TODO: implement the deadline check and the notifications.
    """
    return {"status": "completed", "message": "Checked overdue tasks"}


@celery_app.task(bind=True, name="app.workers.cron_tasks.snapshot_sprint_progress")
def snapshot_sprint_progress(self) -> dict[str, str]:
    """
    Take a daily snapshot of sprint progress.

    Runs daily at 00:00 via Celery Beat.
    TODO: compute and store the burndown chart snapshot.
    """
    return {"status": "completed", "message": "Sprint progress snapshot saved"}
