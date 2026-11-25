"""
WebSocket Connection Manager with Redis Pub/Sub fan-out.

- When broadcast_to_project() is called (from any API worker),
  it publishes to Redis channel ws:projects:{project_id}.
- The background RedisListener subscribes to those channels
  and forwards messages to locally connected WebSocket clients.

This means:
  ✅ Works with multiple uvicorn workers.
  ✅ Notification Worker can push via Redis → browser via WebSocket.
  ✅ Redis connection is pooled (not created per-broadcast).
"""

import json
import logging
import uuid
from collections import defaultdict

import redis.asyncio as aioredis
from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Module-level Redis pool — initialised once in lifespan, shared across all broadcasts.
_redis_pool: aioredis.Redis | None = None


def init_redis_pool(redis_url: str) -> None:
    global _redis_pool
    _redis_pool = aioredis.from_url(
        redis_url, decode_responses=True, max_connections=20
    )


async def close_redis_pool() -> None:
    global _redis_pool
    if _redis_pool:
        await _redis_pool.aclose()
        _redis_pool = None


class ConnectionManager:
    """Manages in-process WebSocket connections and publishes broadcasts via Redis."""

    def __init__(self):
        # project_id → list of connected websockets (local to this process)
        self.active_connections: dict[uuid.UUID, list[WebSocket]] = defaultdict(list)
        # user_id → list of connected websockets (for direct user notifications)
        self.user_connections: dict[str, list[WebSocket]] = defaultdict(list)
        # WS-3: reverse mapping ws → user_id for cleanup on broadcast failure
        self._ws_user: dict[int, str] = {}  # id(ws) → user_id

    # ── Connection Lifecycle ──────────────────────────────────────────

    async def connect(
        self,
        websocket: WebSocket,
        project_id: uuid.UUID | None = None,
        user_id: str | None = None,
    ):
        await websocket.accept()
        if project_id:
            self.active_connections[project_id].append(websocket)
        if user_id:
            self.user_connections[user_id].append(websocket)
            self._ws_user[id(websocket)] = user_id  # WS-3: track mapping
        logger.info("WS connected: project=%s user=%s", project_id, user_id)

    def disconnect(
        self,
        websocket: WebSocket,
        project_id: uuid.UUID | None = None,
        user_id: str | None = None,
    ):
        if project_id and project_id in self.active_connections:
            try:
                self.active_connections[project_id].remove(websocket)
            except ValueError:
                pass
            if not self.active_connections[project_id]:
                del self.active_connections[project_id]

        # WS-3: resolve user_id from reverse mapping if not provided
        resolved_user_id = user_id or self._ws_user.get(id(websocket))
        if resolved_user_id and resolved_user_id in self.user_connections:
            if websocket in self.user_connections[resolved_user_id]:
                self.user_connections[resolved_user_id].remove(websocket)
            if not self.user_connections[resolved_user_id]:
                del self.user_connections[resolved_user_id]

        # WS-3: cleanup reverse mapping
        self._ws_user.pop(id(websocket), None)

    # ── Local Broadcast (called by RedisListener) ─────────────────────

    async def _local_broadcast_to_project(self, project_id: uuid.UUID, message: dict):
        """Forward message to all locally connected clients for a project."""
        connections = list(self.active_connections.get(project_id, []))
        disconnected = []
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.error("Error sending WS message: %s", e)
                disconnected.append(ws)
        for ws in disconnected:
            # WS-3: disconnect() now resolves user_id from _ws_user mapping automatically
            self.disconnect(ws, project_id)

    async def _local_send_to_user(self, user_id: str, message: dict):
        """Forward message to all locally connected clients of a user."""
        connections = list(self.user_connections.get(user_id, []))
        disconnected = []
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.error("Error sending user WS message: %s", e)
                disconnected.append(ws)
        for ws in disconnected:
            self.disconnect(ws, None, user_id)

    # ── Redis-backed Broadcast (called from HTTP handlers) ────────────

    async def broadcast_to_project(self, project_id: uuid.UUID, message: dict):
        """
        Publish an invalidation message for a project via the shared Redis pool.
        Falls back to local broadcast if Redis is unavailable.
        """
        if _redis_pool is not None:
            try:
                channel = f"ws:projects:{project_id}"
                await _redis_pool.publish(channel, json.dumps(message))
                return
            except Exception as e:
                logger.warning("Redis publish failed, falling back to local: %s", e)

        await self._local_broadcast_to_project(project_id, message)


manager = ConnectionManager()
