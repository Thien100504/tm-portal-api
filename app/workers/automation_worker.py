"""
Automation Worker - consumes automation events from RabbitMQ.

Two jobs run side by side:
  1. Dependency unblocking: on task.completed, unblock dependent tasks (auto_start)
  2. DB-driven automation rules: on task events, read automation_rules,
     evaluate the conditions and run the actions (change status, priority, sprint...)

This worker runs as a separate process.
"""

import asyncio
import json
import logging
import signal
import uuid as uuid_lib
from typing import Any

import pika
from pika.adapters.blocking_connection import BlockingChannel
from pika.spec import Basic, BasicProperties
from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.events.publisher import EventPublisher
from app.logging_config import correlation_id_var, setup_logging
from app.models.task import Task, TaskDependency

setup_logging(service_name="automation_worker", level="INFO")
logger = logging.getLogger("automation_worker")

_running: bool = True
_worker_loop: asyncio.AbstractEventLoop | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _broadcast_project(project_id, actor_id: str = "automation"):
    """Notify all WS clients in the project to re-fetch tasks."""
    import redis.asyncio as aioredis

    settings = get_settings()
    try:
        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        msg = json.dumps(
            {"action": "invalidate", "entity": "tasks", "actor_id": actor_id}
        )
        await client.publish(f"ws:projects:{project_id}", msg)
        await client.aclose()
    except Exception as e:
        logger.warning("Redis broadcast failed: %s", e)


# ── Feature 1: Dependency unblocking ─────────────────────────────────────────


async def handle_task_completed(task_id_str: str) -> None:
    """When a task is completed, unblock the dependent tasks that are ready."""
    try:
        task_id = uuid_lib.UUID(task_id_str)
    except ValueError:
        logger.error("Invalid task_id: %s", task_id_str)
        return

    async with AsyncSessionLocal() as db:
        deps_query = (
            select(Task)
            .join(TaskDependency, Task.id == TaskDependency.task_id)
            .where(TaskDependency.depends_on_id == task_id, Task.is_deleted.is_(False))
        )
        dependent_tasks = (await db.execute(deps_query)).scalars().all()

        if not dependent_tasks:
            return

        for dep_task in dependent_tasks:
            if dep_task.status in ["done", "in_progress"]:
                continue

            all_deps_query = (
                select(Task)
                .join(TaskDependency, Task.id == TaskDependency.depends_on_id)
                .where(
                    TaskDependency.task_id == dep_task.id,
                    Task.status != "done",
                    Task.is_deleted.is_(False),
                )
            )
            unfinished = (await db.execute(all_deps_query)).scalars().all()

            if not unfinished:
                if dep_task.auto_start:
                    dep_task.status = "in_progress"
                    await db.commit()
                    logger.info("🚀 Auto-started Task %s (all deps done)", dep_task.id)
                    with EventPublisher() as pub:
                        pub.publish(
                            "task.updated",
                            {"task_id": str(dep_task.id), "title": dep_task.title},
                        )
                        pub.publish(
                            "task.unblocked",
                            {"task_id": str(dep_task.id), "title": dep_task.title},
                        )
                else:
                    from app.models.task import Comment

                    user_id = dep_task.assignee_id or dep_task.created_by
                    if user_id:
                        comment = Comment(
                            task_id=dep_task.id,
                            user_id=user_id,
                            content="✅ All blocking tasks are done. You can start working on this task.",
                        )
                        db.add(comment)
                        await db.commit()
                        logger.info(
                            "🔔 Notified Task %s via comment (auto_start=False)",
                            dep_task.id,
                        )
                        with EventPublisher() as pub:
                            pub.publish(
                                "task.unblocked",
                                {"task_id": str(dep_task.id), "title": dep_task.title},
                            )


# ── Feature 2: DB-driven automation rules ────────────────────────────────────

# BR-AUTO-05: TTL of the dedup guard (300 s = 5 minutes, see BR-AUTO-06)
_AUTOMATION_DEDUP_TTL = 300


async def _is_automation_loop(task_id_str: str, trigger_event: str) -> bool:
    """
    BR-AUTO-05: check whether (task_id, trigger_event) was already handled by
    automation in the last 5 minutes. If so it is a loop and is skipped.
    Redis SET NX (set if not exists) checks and marks atomically.
    """
    settings = get_settings()
    dedup_key = f"automation:dedup:{task_id_str}:{trigger_event}"
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL)
        # SET NX: True when the key did not exist (first time), None when it did (loop)
        is_new = await r.set(dedup_key, "1", nx=True, ex=_AUTOMATION_DEDUP_TTL)
        await r.aclose()
        if is_new is None:  # the key exists: this is a loop
            logger.warning(
                "🔄 BR-AUTO-05: Automation loop detected for task=%s event=%s — skipping",
                task_id_str,
                trigger_event,
            )
            return True
        return False
    except Exception:
        logger.debug("Redis dedup check skipped (connection unavailable)")
        return False  # fail-open: if Redis is down, rules still run


async def handle_automation_rules(
    routing_key: str,
    task_id_str: str,
    context: dict,
) -> None:
    """
    Read automation_rules from the DB, evaluate and run them.
    routing_key map → trigger_event:
      task.created    → task.created
      task.updated    → task.priority_changed (when the context has old_priority)
      task.completed  → task.status_changed (new_status=done)
      task.assigned   → task.assigned

    BR-AUTO-05: infinite loops are prevented by a Redis dedup guard.
    """
    from app.modules.automation.manager import automation_manager

    trigger_map = {
        "task.created": "task.created",
        "task.assigned": "task.assigned",
        "task.completed": "task.status_changed",
        "task.updated": "task.priority_changed",
        "task.unblocked": "task.unblocked",
    }
    trigger_event = trigger_map.get(routing_key)
    if not trigger_event:
        return

    # Add context for status_changed when routing_key=task.completed
    if routing_key == "task.completed":
        context = {**context, "new_status": "done"}

    try:
        task_id = uuid_lib.UUID(task_id_str)
    except ValueError:
        logger.error("Invalid task_id: %s", task_id_str)
        return

    # ── BR-AUTO-05: infinite loop guard ─────────────────────────────────────
    if await _is_automation_loop(task_id_str, trigger_event):
        return

    async with AsyncSessionLocal() as db:
        task = await db.get(Task, task_id)
        if not task or task.is_deleted:
            return

        executed = await automation_manager.execute_rules(
            db, task.project_id, trigger_event, task, context=context
        )
        if executed:
            await db.commit()
            await _broadcast_project(task.project_id)
            logger.info(
                "⚡ %d automation rule(s) executed for %s on %s",
                executed,
                trigger_event,
                task_id,
            )


# ── RabbitMQ message handler ──────────────────────────────────────────────────


def on_message(
    channel: BlockingChannel,
    method: Basic.Deliver,
    properties: BasicProperties,
    body: bytes,
) -> None:
    try:
        payload: dict[str, Any] = json.loads(body)
        cid = payload.pop("correlation_id", properties.correlation_id or "-")
        correlation_id_var.set(cid)
        routing_key = method.routing_key
        logger.info("📥 Event | key=%s cid=%s", routing_key, cid)

        task_id = payload.get("task_id")
        if not task_id:
            channel.basic_ack(delivery_tag=method.delivery_tag)
            return

        assert _worker_loop is not None, "Event loop not initialized"
        # Always try to execute DB-stored automation rules
        if payload.get("source") != "ai_breakdown":
            _worker_loop.run_until_complete(
                handle_automation_rules(routing_key, task_id, context=payload)
            )

        # Additionally handle dependency unblocking for task.completed
        if routing_key == "task.completed":
            _worker_loop.run_until_complete(handle_task_completed(task_id))

        channel.basic_ack(delivery_tag=method.delivery_tag)

    except Exception as exc:
        logger.exception("❌ Error processing message: %s", exc)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def _shutdown_handler(signum: int, frame: Any) -> None:
    global _running
    logger.info("🛑 Shutdown signal received (signal=%s)", signum)
    _running = False


def main() -> None:
    global _running, _worker_loop
    settings = get_settings()

    signal.signal(signal.SIGINT, _shutdown_handler)
    signal.signal(signal.SIGTERM, _shutdown_handler)

    _worker_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_worker_loop)

    logger.info("🚀 Automation Worker starting...")

    connection = pika.BlockingConnection(pika.URLParameters(settings.RABBITMQ_URL))
    channel = connection.channel()

    channel.exchange_declare(
        exchange="task_manager", exchange_type="topic", durable=True
    )
    channel.queue_declare(queue="automation_queue", durable=True)

    # Listen to ALL task events (not just task.completed)
    for routing_key in [
        "task.created",
        "task.updated",
        "task.completed",
        "task.assigned",
        "task.unblocked",
    ]:
        channel.queue_bind(
            queue="automation_queue",
            exchange="task_manager",
            routing_key=routing_key,
        )

    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(
        queue="automation_queue", on_message_callback=on_message, auto_ack=False
    )

    logger.info("⏳ Automation Worker ready, listening on automation_queue...")

    try:
        while _running:
            connection.process_data_events(time_limit=1)
    except Exception as exc:
        logger.exception("❌ Worker error: %s", exc)
    finally:
        try:
            connection.close()
        except Exception:
            pass
        logger.info("👋 Automation Worker stopped.")


if __name__ == "__main__":
    main()
