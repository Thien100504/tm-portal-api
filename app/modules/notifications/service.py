"""
Notification Service — HTTP client for the Notification microservice.

Instead of querying the notification DB directly, portal-api delegates
all notification reads to the notification service's REST API.

Notification writes go through RabbitMQ (event pipeline → publisher →
notification worker), keeping data ownership with the notification service.

For backward compatibility during migration, create_and_push() publishes
via RabbitMQ with routing_key "notification.direct" so the worker can
process it as an in-app notification.
"""

import json
import logging
import uuid
from typing import Optional

import httpx
from fastapi import HTTPException

from app.config import get_settings
from app.events.publisher import EventPublisher

logger = logging.getLogger(__name__)
settings = get_settings()

_BASE = settings.NOTIFICATION_SERVICE_URL
# Shared secret checked by the notification service (empty in local development)
_HEADERS = (
    {"X-Internal-Token": settings.INTERNAL_API_TOKEN}
    if settings.INTERNAL_API_TOKEN
    else {}
)


# ── Query helpers (proxy to notification service HTTP API) ─────────


async def get_for_user(
    db,  # kept for interface compatibility, not used
    user_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=5.0, headers=_HEADERS) as client:
            resp = await client.get(
                f"{_BASE}/notifications",
                params={"user_id": str(user_id), "limit": limit, "offset": offset},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("Notification service query failed: %s", exc)
        raise HTTPException(status_code=503, detail="server.notification_unavailable")


async def get_unread_count(db, user_id: uuid.UUID) -> int:
    try:
        async with httpx.AsyncClient(timeout=5.0, headers=_HEADERS) as client:
            resp = await client.get(
                f"{_BASE}/notifications/unread-count",
                params={"user_id": str(user_id)},
            )
            resp.raise_for_status()
            return resp.json().get("count", 0)
    except Exception as exc:
        logger.warning("Notification service unread-count failed: %s", exc)
        raise HTTPException(status_code=503, detail="server.notification_unavailable")


async def mark_read(db, notif_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0, headers=_HEADERS) as client:
            resp = await client.patch(
                f"{_BASE}/notifications/{notif_id}/read",
                params={"user_id": str(user_id)},
            )
            if resp.status_code == 404:
                return False
            resp.raise_for_status()  # other errors are reported as 503 below
            return True
    except Exception as exc:
        logger.warning("Notification service mark_read failed: %s", exc)
        raise HTTPException(status_code=503, detail="server.notification_unavailable")


async def mark_all_read(db, user_id: uuid.UUID) -> int:
    try:
        async with httpx.AsyncClient(timeout=5.0, headers=_HEADERS) as client:
            resp = await client.patch(
                f"{_BASE}/notifications/read-all",
                params={"user_id": str(user_id)},
            )
            resp.raise_for_status()
            return resp.json().get("marked_read", 0)
    except Exception as exc:
        logger.warning("Notification service mark_all_read failed: %s", exc)
        raise HTTPException(status_code=503, detail="server.notification_unavailable")


# ── Write helpers (publish to RabbitMQ → notification worker) ─────


def _publish_notification_sync(payload: dict) -> None:
    try:
        with EventPublisher() as pub:
            pub.publish("notification.direct", payload)
    except Exception:
        logger.exception("Failed to publish direct notification to RabbitMQ")


async def push_via_redis(data: dict) -> None:
    """Push notification to Redis for WebSocket delivery (best-effort)."""
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        user_id = data.get("user_id")
        if user_id:
            channel = f"notifications:{user_id}"
            await client.publish(channel, json.dumps(data))
        await client.aclose()
    except Exception as exc:
        logger.warning("Notification Redis push failed: %s", exc)


async def create_and_push(
    db,  # kept for interface compatibility
    *,
    user_id: uuid.UUID,
    title: Optional[str] = None,
    title_key: Optional[str] = None,
    title_params: Optional[dict] = None,
    event_type: Optional[str] = None,
    event_data: Optional[dict] = None,
    message: Optional[str] = None,
    message_key: Optional[str] = None,
    message_params: Optional[dict] = None,
    type: str = "info",
    entity_type: Optional[str] = None,
    entity_id: Optional[uuid.UUID] = None,
    project_id: Optional[uuid.UUID] = None,
) -> dict:
    """
    Publish notification to RabbitMQ for the notification worker to persist.
    The worker stores it and pushes it to Redis for WebSocket delivery
    (pushing here as well delivered every notification twice).

    Prefer title_key/message_key (i18n dot-notation) over raw title/message strings.
    FE renders via t(title_key, title_params) with fallback to title.
    """
    payload = {
        # The worker dedups on event + user + task/project: use the most specific
        # event name so different notifications for one user are not dropped
        "event": event_type or title_key or "notification.direct",
        "user_id": str(user_id),
        "title": title,
        "title_key": title_key,
        "title_params": title_params,
        "message": message,
        "message_key": message_key,
        "message_params": message_params,
        "type": type,
        "entity_type": entity_type,
        "entity_id": str(entity_id) if entity_id else None,
        "project_id": str(project_id) if project_id else None,
        "task_id": str(entity_id) if entity_id and entity_type == "task" else None,
        "channels": ["inapp"],
    }
    if event_data:
        payload["data"] = event_data  # type: ignore[assignment]

    from fastapi.concurrency import run_in_threadpool

    await run_in_threadpool(_publish_notification_sync, payload)

    return payload
