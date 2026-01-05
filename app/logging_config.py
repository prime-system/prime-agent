"""Structured logging configuration with JSON output."""

from __future__ import annotations

import logging
import sys

try:
    from pythonjsonlogger import jsonlogger
except ImportError:
    jsonlogger = None  # type: ignore


class RequestIDFilter(logging.Filter):
    """Add request ID to log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Add request_id field to log record."""
        from app.utils.request_context import get_request_id

        record.request_id = get_request_id() or "no-request-id"  # type: ignore[attr-defined]
        return True


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

    if use_json and jsonlogger is not None:
        # JSON formatter with structured fields including request_id
        json_formatter = jsonlogger.JsonFormatter(
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


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)
