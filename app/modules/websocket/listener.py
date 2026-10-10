"""
Redis Pub/Sub Listener

Subscribes to Redis channels and forwards messages to local WebSocket clients.

Channels subscribed:
  - ws:projects:*   → broadcast invalidation to all members in that project
  - notifications:* → push personal notification to a specific user
"""

import asyncio
import json
import logging
import uuid

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


async def redis_listener(redis_url: str):
    """
    Long-running background coroutine started in FastAPI lifespan.
    Subscribes to Redis pub/sub and forwards messages to WebSocket clients.
    """
    from app.modules.websocket.manager import manager

    while True:
        try:
            redis_client = aioredis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
                health_check_interval=30,
            )
            pubsub = redis_client.pubsub()

            await pubsub.psubscribe("ws:projects:*", "notifications:*")
            logger.info(
                "🔌 Redis listener started: subscribed to ws:projects:* and notifications:*"
            )

            async for raw_message in pubsub.listen():
                if raw_message["type"] not in ("pmessage", "message"):
                    continue

                channel: str = raw_message.get("channel", "")
                data_str: str = raw_message.get("data", "{}")

                try:
                    payload = json.loads(data_str)
                except json.JSONDecodeError:
                    logger.warning(
                        "Invalid JSON from Redis channel %s: %s", channel, data_str
                    )
                    continue

                # ── ws:projects:{project_id} → broadcast to project room ──
                if channel.startswith("ws:projects:"):
                    project_id_str = channel.removeprefix("ws:projects:")
                    try:
                        project_id = uuid.UUID(project_id_str)
                        await manager._local_broadcast_to_project(project_id, payload)
                    except ValueError:
                        logger.warning("Invalid project_id in channel: %s", channel)

                # ── notifications:{user_id} → send to user's WebSocket ──
                elif channel.startswith("notifications:"):
                    user_id = channel.removeprefix("notifications:")
                    notification_payload = {"action": "notification", **payload}
                    await manager._local_send_to_user(user_id, notification_payload)

        except asyncio.CancelledError:
            logger.info("Redis listener cancelled.")
            break
        except Exception as e:
            logger.warning("Redis listener error: %s — reconnecting in 5s...", e)
            await asyncio.sleep(5)
