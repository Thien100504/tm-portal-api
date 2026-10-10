"""
Request ID Middleware.

Generates a unique correlation ID for each HTTP request and:
  1. Sets it in a ContextVar (available to all loggers in that request)
  2. Returns it in the X-Request-ID response header
  3. Logs request method, path, status, and duration as structured JSON
"""

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.logging_config import correlation_id_var

logger = logging.getLogger("request")


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]

        token = correlation_id_var.set(request_id)

        start = time.monotonic()
        try:
            response = await call_next(request)
        finally:
            duration_ms = round((time.monotonic() - start) * 1000, 1)
            correlation_id_var.reset(token)

        response.headers["X-Request-ID"] = request_id

        if not request.url.path.startswith(("/docs", "/redoc", "/openapi.json")):
            logger.info(
                "%s %s → %s (%.1fms)",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
                extra={
                    "method": request.method,
                    "path": str(request.url.path),
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                    "correlation_id": request_id,
                },
            )

        return response
