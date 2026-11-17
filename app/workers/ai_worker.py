"""
AI Worker - consumes AI jobs from RabbitMQ.

Uses pika (NOT Celery) to receive messages from ai_queue.
This worker runs as a separate process.

How to run:
    python -m app.workers.ai_worker
"""

import json
import logging
import signal
from typing import Any
import asyncio
import uuid
import redis.asyncio as redis

import pika
from pika.adapters.blocking_connection import BlockingChannel
from pika.spec import Basic, BasicProperties
from openai import OpenAI

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.task import Task
from sqlalchemy import select, func

from app.logging_config import setup_logging, correlation_id_var

# Module-level event loop reference – assigned in main() before use
_worker_loop: asyncio.AbstractEventLoop | None = None
_running: bool = True

setup_logging(service_name="ai_worker", level="INFO")
logger = logging.getLogger("ai_worker")

settings = get_settings()

from app.models.ai import AIMetric

client = OpenAI(base_url=settings.NVIDIA_BASE_URL, api_key=settings.NVIDIA_API_KEY)

MODEL_NAME = "meta/llama-3.1-70b-instruct"


async def _record_metric(
    feature: str,
    project_id: str,
    task_id: str,
    actor_id: str,
    model_used: str,
    response_time_ms: int,
    output_data: dict,
    status: str = "generated",
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> str | None:
    """Record AI metric and return metric ID for frontend feedback tracking."""
    try:
        async with AsyncSessionLocal() as db:
            metric = AIMetric(
                project_id=uuid.UUID(project_id),
                task_id=uuid.UUID(task_id) if task_id else None,
                user_id=uuid.UUID(actor_id) if actor_id else None,
                feature=feature,
                model_used=model_used,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                response_time_ms=response_time_ms,
                output_data=output_data,
                status=status,
                correlation_id=correlation_id_var.get("-"),
            )
            db.add(metric)
            await db.commit()
            return str(metric.id)
    except Exception as e:
        logger.warning("Failed to record AI metric: %s", e)
        return None


async def notify_clients(project_id: str, actor_id: str, ai_result: dict | None = None):
    redis_client = redis.from_url(
        settings.REDIS_URL, encoding="utf-8", decode_responses=True
    )
    channel = f"ws:projects:{project_id}"
    payload: dict[str, object] = {"action": "invalidate", "entity": "tasks"}
    if ai_result:
        payload["ai_result"] = ai_result
    await redis_client.publish(channel, json.dumps(payload))
    await redis_client.aclose()


MAX_AI_SUBTASKS = 10
FIBONACCI_POINTS = {1, 2, 3, 5, 8, 13, 21}


async def process_ai_breakdown(payload: dict):
    task_id = payload.get("task_id")
    title = payload.get("title")
    description = payload.get("description", "")
    project_id = payload.get("project_id")
    actor_id = payload.get("actor_id")

    # Anti-duplication: Redis lock per task (60s TTL)
    import redis as sync_redis

    r = sync_redis.from_url(settings.REDIS_URL)
    lock_key = f"ai_breakdown_lock:{task_id}"
    acquired = r.set(lock_key, "1", ex=60, nx=True)
    if not acquired:
        logger.info(f"Skipping duplicate AI breakdown for task {task_id} (lock held)")
        return

    try:
        await _do_ai_breakdown(task_id, title, description, project_id, actor_id)
    finally:
        r.delete(lock_key)


async def _do_ai_breakdown(task_id, title, description, project_id, actor_id):
    prompt = f"""
You are an expert project manager. I have a task titled "{title}" with the following description:
"{description}"

Please break down this task into 3 to 5 logical subtasks.
Return ONLY a valid JSON array of objects, where each object has a single key "title" containing the subtask title (in the same language as the original task).
Example:
[
  {{"title": "Subtask 1"}},
  {{"title": "Subtask 2"}}
]
"""
    import time as _time

    logger.info(f"Generating breakdown for task {task_id}")
    t0 = _time.monotonic()
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        top_p=0.8,
        max_tokens=1024,
    )
    elapsed_ms = int((_time.monotonic() - t0) * 1000)
    content = response.choices[0].message.content.strip()
    usage = response.usage

    # Qwen3 reasoning models emit <think>...</think> before the JSON; strip it
    import re

    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

    if content.startswith("```json"):
        content = content[7:]
        content = content[: content.rfind("```")].strip()
    elif content.startswith("```"):
        content = content[3:]
        content = content[: content.rfind("```")].strip()

    try:
        subtasks_data = json.loads(content.strip())
    except Exception as e:
        logger.error(f"Failed to parse LLM JSON: {content!r}")
        raise e
    if isinstance(subtasks_data, dict):
        subtasks_data = subtasks_data.get("subtasks", [])
    if not isinstance(subtasks_data, list):
        raise ValueError("AI breakdown did not return a list")
    titles = []
    for item in subtasks_data[:MAX_AI_SUBTASKS]:
        raw = item.get("title") if isinstance(item, dict) else item
        title = str(raw).strip()[:255] if raw is not None else ""
        if title:
            titles.append(title)

    async with AsyncSessionLocal() as db:
        from sqlalchemy import update
        from datetime import datetime, timezone

        actor_uuid = uuid.UUID(actor_id) if actor_id else None

        # The parent decides the project and sprint; a deleted parent stops the job
        parent_task = await db.get(Task, uuid.UUID(task_id))
        if not parent_task or parent_task.is_deleted:
            logger.warning("AI breakdown skipped: task %s no longer exists", task_id)
            return None
        parent_project_id = parent_task.project_id
        parent_sprint_id = parent_task.sprint_id

        # Replace only the subtasks an earlier AI breakdown created that are still
        # "todo"; subtasks written by people are kept
        previous = await db.execute(
            select(AIMetric.output_data).where(
                AIMetric.feature == "breakdown",
                AIMetric.task_id == parent_task.id,
            )
        )
        old_ids = [
            uuid.UUID(i)
            for data in previous.scalars()
            for i in ((data or {}).get("created_ids") or [])
        ]
        if old_ids:
            await db.execute(
                update(Task)
                .where(
                    Task.id.in_(old_ids),
                    Task.parent_task_id == parent_task.id,
                    Task.status == "todo",
                    Task.is_deleted.is_(False),
                )
                .values(
                    is_deleted=True,
                    deleted_at=datetime.now(timezone.utc),
                    deleted_by=actor_uuid,
                )
            )
            await db.flush()

        max_pos_query = select(func.max(Task.position)).where(
            Task.project_id == parent_project_id,
            Task.status == "todo",
            Task.is_deleted.is_(False),
        )
        max_pos = (await db.execute(max_pos_query)).scalar() or 0

        created_task_ids = []
        for i, title in enumerate(titles):
            new_task = Task(
                project_id=parent_project_id,
                parent_task_id=parent_task.id,
                workspace_id=parent_task.workspace_id,
                sprint_id=parent_sprint_id,
                title=title,
                status="todo",
                priority="medium",
                position=max_pos + i + 1,
                created_by=uuid.UUID(actor_id) if actor_id else None,
            )
            db.add(new_task)
            await db.flush()
            created_task_ids.append(str(new_task.id))
        await db.commit()

    # Publish task.created events so automation rules + audit pipeline fire
    from app.events.publisher import EventPublisher

    try:
        with EventPublisher() as pub:
            for new_id in created_task_ids:
                pub.publish(
                    "task.created",
                    {
                        "task_id": new_id,
                        "project_id": project_id,
                        "actor_id": actor_id,
                        "source": "ai_breakdown",
                    },
                )
    except Exception:
        logger.warning("Failed to publish task.created events for AI subtasks")

    metric_id = await _record_metric(
        feature="breakdown",
        project_id=project_id,
        task_id=task_id,
        actor_id=actor_id,
        model_used=MODEL_NAME,
        response_time_ms=elapsed_ms,
        output_data={
            "subtasks": titles,
            "count": len(titles),
            "created_ids": created_task_ids,
        },
        input_tokens=usage.prompt_tokens if usage else None,
        output_tokens=usage.completion_tokens if usage else None,
    )
    await notify_clients(
        project_id,
        actor_id,
        ai_result={
            "feature": "breakdown",
            "metric_id": metric_id,
            "task_id": task_id,
            "count": len(titles),
        },
    )


async def process_ai_estimate(payload: dict):
    task_id: str = payload.get("task_id") or ""
    title: str = payload.get("title") or ""
    description: str = payload.get("description") or ""
    project_id: str = payload.get("project_id") or ""
    actor_id: str = payload.get("actor_id") or ""

    prompt = f"""
You are an expert Agile project manager. I have a task titled "{title}" with the following description:
"{description}"

Please estimate the complexity of this task using Agile Story Points (Fibonacci sequence: 1, 2, 3, 5, 8, 13, 21).
Return ONLY a valid JSON object with a single key "story_points" containing the integer Fibonacci number.
Example:
{{"story_points": 5}}
"""
    import time as _time

    logger.info(f"Generating estimate for task {task_id}")
    t0 = _time.monotonic()
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        top_p=0.8,
        max_tokens=512,
    )
    elapsed_ms = int((_time.monotonic() - t0) * 1000)
    content = (response.choices[0].message.content or "").strip()
    usage = response.usage

    # Strip <think>...</think> from Qwen3 reasoning models
    import re

    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

    if content.startswith("```json"):
        content = content[7:]
        content = content[: content.rfind("```")].strip()
    elif content.startswith("```"):
        content = content[3:]
        content = content[: content.rfind("```")].strip()

    try:
        data = json.loads(content.strip())
        story_points = int(data.get("story_points", 0))
    except Exception as e:
        logger.error(f"Failed to parse LLM JSON: {content!r}")
        raise e
    if story_points not in FIBONACCI_POINTS:
        raise ValueError(f"AI estimate is not a Fibonacci number: {story_points}")

    async with AsyncSessionLocal() as db:
        task = await db.get(Task, uuid.UUID(task_id))
        if task and not task.is_deleted:
            task.story_points = story_points
            await db.commit()

    metric_id = await _record_metric(
        feature="estimate",
        project_id=project_id,
        task_id=task_id,
        actor_id=actor_id,
        model_used=MODEL_NAME,
        response_time_ms=elapsed_ms,
        output_data={"story_points": story_points},
        input_tokens=usage.prompt_tokens if usage else None,
        output_tokens=usage.completion_tokens if usage else None,
    )
    await notify_clients(
        project_id,
        actor_id,
        ai_result={
            "feature": "estimate",
            "metric_id": metric_id,
            "task_id": task_id,
            "story_points": story_points,
        },
    )


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
        logger.info(
            "📥 AI message received | routing_key=%s cid=%s", method.routing_key, cid
        )

        assert _worker_loop is not None, "Event loop not initialized"
        if method.routing_key == "task.ai.breakdown":
            _worker_loop.run_until_complete(process_ai_breakdown(payload))
        elif method.routing_key == "task.ai.estimate":
            _worker_loop.run_until_complete(process_ai_estimate(payload))

        channel.basic_ack(delivery_tag=method.delivery_tag)
        logger.info("✅ Processed | delivery_tag=%s", method.delivery_tag)

    except json.JSONDecodeError:
        logger.error("❌ Could not parse JSON: %s", body)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
    except Exception as exc:
        logger.exception("❌ Failed to process message: %s", exc)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def _shutdown_handler(signum: int, frame: Any) -> None:
    """Handle shutdown signals gracefully."""
    global _running
    logger.info("🛑 Shutdown signal received (signal=%s), stopping...", signum)
    _running = False


def main() -> None:
    """Start the AI worker consumer."""
    global _running

    settings = get_settings()

    # Register signal handlers for a graceful shutdown
    signal.signal(signal.SIGINT, _shutdown_handler)
    signal.signal(signal.SIGTERM, _shutdown_handler)

    # Create a global event loop for all async DB operations
    global _worker_loop
    _worker_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_worker_loop)

    logger.info("🚀 AI Worker starting...")

    # Connect to RabbitMQ
    connection_params = pika.URLParameters(settings.RABBITMQ_URL)
    connection = pika.BlockingConnection(connection_params)
    channel = connection.channel()

    # Declare the exchange (idempotent, safe if it exists)
    channel.exchange_declare(
        exchange="task_manager", exchange_type="topic", durable=True
    )

    # Declare the queue
    channel.queue_declare(queue="ai_queue", durable=True)

    # Prefetch: process one message at a time
    channel.basic_qos(prefetch_count=1)

    # Register the consumer
    channel.queue_bind(
        exchange="task_manager", queue="ai_queue", routing_key="task.ai.*"
    )
    channel.basic_consume(
        queue="ai_queue",
        on_message_callback=on_message,
        auto_ack=False,
    )

    logger.info("⏳ AI Worker ready, waiting for messages on ai_queue...")

    try:
        while _running:
            # Process events with a timeout so that _running is checked
            connection.process_data_events(time_limit=1)
    except Exception as exc:
        logger.exception("❌ AI Worker error: %s", exc)
    finally:
        logger.info("🛑 Closing the connection...")
        try:
            connection.close()
        except Exception:
            pass
        logger.info("👋 AI Worker stopped.")


if __name__ == "__main__":
    main()
