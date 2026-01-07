"""Structured logging configuration with JSON output."""

from __future__ import annotations

import logging
import sys
from typing import Any

_jsonlogger: Any | None
try:
    from pythonjsonlogger import jsonlogger as _jsonlogger
except ImportError:
    _jsonlogger = None

jsonlogger: Any | None = _jsonlogger
JsonFormatter: Any = getattr(jsonlogger, "JsonFormatter", None)


class RequestIDFilter(logging.Filter):
    """Add request ID to log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Add request_id field to log record."""
        from app.utils.request_context import get_request_id

        record.request_id = get_request_id() or "no-request-id"
        return True


class HealthCheckFilter(logging.Filter):
    """Suppress access logs for successful health check endpoints.

    Only filters out 200 OK responses - errors (4xx, 5xx) are still logged.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter out successful health check endpoint logs."""
        message = record.getMessage()

        # Only suppress successful (200) health check requests
        health_paths = [
            "GET /health ",
            "GET /health/ready ",
            "GET /health/detailed ",
        ]

        return all(not (path in message and '" 200' in message) for path in health_paths)


def configure_json_logging(
    log_level: str = "INFO",
    use_json: bool = True,
) -> None:
    """Configure application logging with optional JSON output.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        use_json: Whether to use JSON output (True) or text output (False)
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create stdout handler
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(getattr(logging, log_level.upper()))

    # Add request ID filter to all handlers
    request_id_filter = RequestIDFilter()
    stream_handler.addFilter(request_id_filter)

    if use_json and JsonFormatter is not None:
        # JSON formatter with structured fields including request_id
        json_formatter = JsonFormatter(
            fmt="%(timestamp)s %(level)s %(name)s %(message)s %(request_id)s",
            timestamp=True,
        )
        stream_handler.setFormatter(json_formatter)
    else:
        # Standard text formatter
        text_formatter = logging.Formatter(
            fmt="%(asctime)s - %(name)s - %(levelname)s - [%(request_id)s] - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        stream_handler.setFormatter(text_formatter)

    root_logger.addHandler(stream_handler)

    # Suppress noisy loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)

    # Filter successful health check logs from uvicorn access logger
    uvicorn_access_logger = logging.getLogger("uvicorn.access")
    health_check_filter = HealthCheckFilter()
    uvicorn_access_logger.addFilter(health_check_filter)


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)
