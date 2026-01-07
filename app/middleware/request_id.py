"""
Middleware to add request ID to all requests.

Generates and propagates request IDs across async boundaries for log correlation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

from app.utils.request_context import (
    clear_request_id,
    generate_request_id,
    set_request_id,
)

if TYPE_CHECKING:
    from fastapi import Request

logger = logging.getLogger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware to track request IDs across async contexts."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        """Process request and set request ID in context."""
        # Check if request already has ID (from client)
        request_id = request.headers.get("X-Request-ID")

        if not request_id:
            # Generate new ID
            request_id = generate_request_id()

        # Set in context
        set_request_id(request_id)

        # Skip logging for health check endpoints to reduce noise
        should_log = not request.url.path.startswith("/health")

        # Log request start
        if should_log:
            logger.info(
                "Request started",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                },
            )

        try:
            # Process request
            response = await call_next(request)

            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id

            # Log request completion
            if should_log:
                logger.info(
                    "Request completed",
                    extra={
                        "request_id": request_id,
                        "status_code": response.status_code,
                    },
                )

            return response
        finally:
            # Clear request ID from context
            clear_request_id()
