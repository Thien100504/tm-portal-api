"""
Task Manager API — Entry Point

Includes:
  - CORS middleware
  - Health check
  - API v1 routers (via api_v1.py)
  - WebSocket router
  - Redis pub/sub listener (lifespan background task)
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.logging_config import setup_logging
from app.middleware.request_id import RequestIDMiddleware
from app.api_v1 import api_v1_router
from app.config import get_settings
from app.database import engine
from app.modules.websocket.listener import redis_listener
from app.modules.websocket.manager import init_redis_pool, close_redis_pool
from app.modules.websocket.router import router as ws_router

settings = get_settings()

setup_logging(
    service_name="portal-api", level=settings.LOG_LEVEL, json_output=settings.LOG_JSON
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Manage the application lifecycle.

    Startup:
      - Start the Redis pub/sub listener to receive realtime events
        from other workers and from the Notification Worker.
    Shutdown:
      - Stop the listener, dispose the DB engine.
    """
    print("Task Manager API is starting up...")

    # Shared Redis pool for broadcasts (avoids per-call connection overhead)
    init_redis_pool(settings.REDIS_URL)

    # Start Redis listener as background task
    listener_task = asyncio.create_task(redis_listener(settings.REDIS_URL))

    yield

    # --- Shutdown ---
    print("Task Manager API is shutting down...")
    listener_task.cancel()
    try:
        await asyncio.wait_for(listener_task, timeout=5.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    await close_redis_pool()
    await engine.dispose()


app = FastAPI(
    title="Task Manager API",
    description=(
        "Smart task management API with AI integration, "
        "automation and real-time progress tracking."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    redirect_slashes=False,
)


# ── Exception Handlers ───────────────────────────────────────────────
@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422, content={"detail": "validation.error", "errors": exc.errors()}
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_handler(request: Request, exc: SQLAlchemyError):
    logger.exception("Unhandled DB error on %s %s", request.method, request.url)
    return JSONResponse(status_code=500, content={"detail": "db.unexpected_error"})


@app.exception_handler(Exception)
async def generic_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url)
    return JSONResponse(status_code=500, content={"detail": "server.unexpected_error"})


# ── Middleware (order matters: last added = first executed) ──────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestIDMiddleware)


# ── Health Check ─────────────────────────────────────────────────────
@app.get("/", tags=["health"])
async def health_check() -> dict[str, Any]:
    """System health check."""
    return {"status": "ok", "version": "1.0.0"}


# ── Routers ──────────────────────────────────────────────────────────
app.include_router(api_v1_router)
app.include_router(ws_router, prefix="/ws", tags=["websocket"])
