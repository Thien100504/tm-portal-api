"""
Event Pipeline Framework — inspired by OpenStack TaskFlow.

Features:
  - Linear flow with automatic revert on failure
  - Parallel flow for independent handlers (asyncio.gather)
  - Retry policy with exponential backoff
  - Conditional execution via should_run()
  - Execution persistence for audit trail
  - Pipeline registry for centralized management

Usage:
    pipeline = Pipeline("task_events", [
        MetadataHandler(),                          # sequential
        Parallel(AuditLogHandler(), WebSocketHandler()),  # parallel
        RabbitMQHandler(retry=RetryPolicy(max_retries=2)),
    ])
    await pipeline.run(EventContext(...))
"""

import asyncio
import logging
import time
import uuid as uuid_lib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import correlation_id_var

logger = logging.getLogger("event_pipeline")


# ── Context ──────────────────────────────────────────────────────────────────


@dataclass
class EventContext:
    """Shared context passed through the pipeline. Handlers can read/write to it."""

    db: AsyncSession
    background_tasks: BackgroundTasks
    event_type: str
    task: Any
    actor: Any
    extra: dict = field(default_factory=dict)

    meta: dict = field(default_factory=dict)
    stakeholders: set = field(default_factory=set)
    skip_external: bool = False

    # Populated by Pipeline.run()
    execution_id: str = field(default_factory=lambda: uuid_lib.uuid4().hex[:16])

    @property
    def correlation_id(self) -> str:
        return correlation_id_var.get("-")


# ── Retry Policy ─────────────────────────────────────────────────────────────


@dataclass
class RetryPolicy:
    max_retries: int = 0
    backoff_base: float = 0.5

    def delay(self, attempt: int) -> float:
        return self.backoff_base * (2**attempt)


NO_RETRY = RetryPolicy(max_retries=0)


# ── Handler Base ─────────────────────────────────────────────────────────────


class EventHandler:
    """Base class. Subclass and implement handle()."""

    name: str = "base"
    retry: RetryPolicy = NO_RETRY

    def __init__(self, retry: RetryPolicy | None = None):
        if retry is not None:
            self.retry = retry

    async def should_run(self, ctx: EventContext) -> bool:
        return True

    async def handle(self, ctx: EventContext) -> None:
        raise NotImplementedError

    async def revert(self, ctx: EventContext, error: Exception) -> None:
        pass


# ── Handler Result ───────────────────────────────────────────────────────────


@dataclass
class HandlerResult:
    handler_name: str
    status: str  # "success" | "skipped" | "failed" | "retried"
    duration_ms: float = 0
    attempts: int = 1
    error: str | None = None


# ── Parallel Group ───────────────────────────────────────────────────────────


class Parallel:
    """Wraps multiple handlers to run concurrently via asyncio.gather."""

    name: str = "parallel"

    def __init__(self, *handlers: EventHandler):
        self.handlers = handlers
        self.name = f"parallel({','.join(h.name for h in handlers)})"


# ── Pipeline ─────────────────────────────────────────────────────────────────


class Pipeline:
    """Runs handlers in defined order. Supports sequential + parallel steps."""

    def __init__(self, name: str, handlers: list[EventHandler | Parallel]):
        self.name = name
        self.handlers = handlers
        _registry[name] = self

    async def run(self, ctx: EventContext) -> list[HandlerResult]:
        start = time.monotonic()
        results: list[HandlerResult] = []
        completed_handlers: list[EventHandler] = []

        logger.info(
            "▶ [%s] %s | task=%s actor=%s cid=%s exec=%s",
            self.name,
            ctx.event_type,
            str(ctx.task.id)[:8] if ctx.task else "?",
            ctx.actor.full_name if ctx.actor else "?",
            ctx.correlation_id,
            ctx.execution_id,
        )

        for step in self.handlers:
            if isinstance(step, Parallel):
                step_results = await self._run_parallel(step, ctx)
                results.extend(step_results)
                for r in step_results:
                    if r.status == "success":
                        h = next(
                            (h for h in step.handlers if h.name == r.handler_name), None
                        )
                        if h:
                            completed_handlers.append(h)
                    elif r.status == "failed":
                        await self._revert(
                            completed_handlers,
                            ctx,
                            Exception(r.error or "parallel handler failed"),
                        )
                        break
            else:
                result = await self._run_handler(step, ctx)
                results.append(result)
                if result.status == "success":
                    completed_handlers.append(step)
                elif result.status == "failed":
                    await self._revert(
                        completed_handlers,
                        ctx,
                        Exception(result.error or "handler failed"),
                    )
                    break

        total = (time.monotonic() - start) * 1000
        ok = sum(1 for r in results if r.status in ("success", "skipped"))
        logger.info(
            "■ [%s] %s done | %d/%d handlers | %.1fms | exec=%s",
            self.name,
            ctx.event_type,
            ok,
            len(results),
            total,
            ctx.execution_id,
        )

        self._persist_async(ctx, results, total)
        return results

    async def _run_handler(
        self, handler: EventHandler, ctx: EventContext
    ) -> HandlerResult:
        if not await handler.should_run(ctx):
            return HandlerResult(handler_name=handler.name, status="skipped")

        last_error = None
        max_attempts = handler.retry.max_retries + 1

        for attempt in range(max_attempts):
            try:
                t0 = time.monotonic()
                await handler.handle(ctx)
                elapsed = (time.monotonic() - t0) * 1000
                status = "retried" if attempt > 0 else "success"
                logger.debug(
                    "  ✓ %s (%.1fms, attempt %d)", handler.name, elapsed, attempt + 1
                )
                return HandlerResult(
                    handler_name=handler.name,
                    status=status,
                    duration_ms=elapsed,
                    attempts=attempt + 1,
                )
            except Exception as e:
                last_error = e
                if attempt < max_attempts - 1:
                    delay = handler.retry.delay(attempt)
                    logger.warning(
                        "  ↻ %s attempt %d failed, retrying in %.1fs: %s",
                        handler.name,
                        attempt + 1,
                        delay,
                        e,
                    )
                    await asyncio.sleep(delay)

        logger.exception(
            "  ✗ %s FAILED after %d attempts: %s",
            handler.name,
            max_attempts,
            last_error,
        )
        return HandlerResult(
            handler_name=handler.name,
            status="failed",
            attempts=max_attempts,
            error=str(last_error),
        )

    async def _run_parallel(
        self, group: Parallel, ctx: EventContext
    ) -> list[HandlerResult]:
        async def _wrap(h: EventHandler) -> HandlerResult:
            return await self._run_handler(h, ctx)

        results = await asyncio.gather(
            *(_wrap(h) for h in group.handlers),
            return_exceptions=False,
        )
        return list(results)

    async def _revert(
        self, completed: list[EventHandler], ctx: EventContext, error: Exception
    ) -> None:
        for h in reversed(completed):
            try:
                await h.revert(ctx, error)
                logger.debug("  ⟲ %s reverted", h.name)
            except Exception:
                logger.exception("  ⟲ %s revert failed", h.name)

    def _persist_async(
        self, ctx: EventContext, results: list[HandlerResult], total_ms: float
    ) -> None:
        """Schedule persistence as a background task (non-blocking)."""
        record = {
            "execution_id": ctx.execution_id,
            "pipeline": self.name,
            "event_type": ctx.event_type,
            "correlation_id": ctx.correlation_id,
            "total_ms": round(total_ms, 1),
            "handler_count": len(results),
            "success_count": sum(
                1 for r in results if r.status in ("success", "retried")
            ),
            "skipped_count": sum(1 for r in results if r.status == "skipped"),
            "failed_count": sum(1 for r in results if r.status == "failed"),
            "handlers": [
                {
                    "name": r.handler_name,
                    "status": r.status,
                    "duration_ms": round(r.duration_ms, 1),
                    "attempts": r.attempts,
                    "error": r.error,
                }
                for r in results
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        ctx.background_tasks.add_task(_persist_execution, record)


# ── Persistence ──────────────────────────────────────────────────────────────


async def _persist_execution(record: dict) -> None:
    """Persist pipeline execution to DB as an audit record."""
    try:
        from app.database import AsyncSessionLocal
        from app.models.pipeline import PipelineExecution

        async with AsyncSessionLocal() as db:
            execution = PipelineExecution(
                execution_id=record["execution_id"],
                pipeline_name=record["pipeline"],
                event_type=record["event_type"],
                correlation_id=record["correlation_id"],
                total_ms=record["total_ms"],
                handler_count=record["handler_count"],
                success_count=record["success_count"],
                failed_count=record["failed_count"],
                handlers_detail=record["handlers"],
            )
            db.add(execution)
            await db.commit()
    except Exception:
        logger.warning("Failed to persist pipeline execution", exc_info=True)


# ── Pipeline Registry ────────────────────────────────────────────────────────

_registry: dict[str, Pipeline] = {}


def get_pipeline(name: str) -> Pipeline | None:
    return _registry.get(name)


def get_all_pipelines() -> dict[str, Pipeline]:
    return dict(_registry)
