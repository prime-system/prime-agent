"""Tests for structured JSON logging configuration and output."""

from __future__ import annotations

import json
import logging
from io import StringIO

import pytest

try:
    from app.utils import json_formatter
except ImportError:
    json_formatter = None  # type: ignore


@pytest.fixture
def json_log_handler() -> tuple[StringIO, logging.StreamHandler]:
    """Capture JSON logs for testing."""
    if json_formatter is None:
        pytest.skip("json_formatter not installed")

    log_stream = StringIO()
    handler = logging.StreamHandler(log_stream)
    formatter = json_formatter.JsonFormatter(timestamp=True)
    handler.setFormatter(formatter)

    return log_stream, handler


@pytest.fixture
def json_logger(json_log_handler: tuple[StringIO, logging.StreamHandler]) -> logging.Logger:
    """Create a JSON logger for testing."""
    log_stream, handler = json_log_handler

    logger = logging.getLogger("test_logger")
    logger.handlers.clear()  # Clear any existing handlers
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    yield logger

    # Cleanup
    logger.removeHandler(handler)
    handler.close()


def test_structured_logging_outputs_json(json_logger: logging.Logger) -> None:
    """Verify logs are output as valid JSON."""
    json_logger.info("Test message", extra={"field1": "value1"})

    # Get log output
    handler = json_logger.handlers[0]
    stream = handler.stream  # type: ignore
    log_output = stream.getvalue()

    # Parse JSON
    log_data = json.loads(log_output.strip())

    # Verify structure
    assert log_data["message"] == "Test message"
    assert log_data["field1"] == "value1"
    assert log_data["level"] == "INFO"
    assert "timestamp" in log_data


def test_structured_logging_captures_extra_fields(json_logger: logging.Logger) -> None:
    """Verify extra fields are captured in JSON."""
    json_logger.info(
        "Capture event",
        extra={
            "dump_id": "test-id",
            "source": "iphone",
            "size_bytes": 1024,
        },
    )

    handler = json_logger.handlers[0]
    stream = handler.stream  # type: ignore
    log_data = json.loads(stream.getvalue().strip())

    assert log_data["dump_id"] == "test-id"
    assert log_data["source"] == "iphone"
    assert log_data["size_bytes"] == 1024
    assert log_data["message"] == "Capture event"


def test_structured_logging_handles_multiple_fields(json_logger: logging.Logger) -> None:
    """Verify multiple extra fields are correctly captured."""
    json_logger.info(
        "Processing completed",
        extra={
            "duration_seconds": 45.23,
            "cost_usd": 0.0123,
            "files_count": 5,
            "success": True,
        },
    )

    handler = json_logger.handlers[0]
    stream = handler.stream  # type: ignore
    log_data = json.loads(stream.getvalue().strip())

    assert log_data["duration_seconds"] == 45.23
    assert log_data["cost_usd"] == 0.0123
    assert log_data["files_count"] == 5
    assert log_data["success"] is True


def test_structured_logging_error_with_exc_info(json_logger: logging.Logger) -> None:
    """Verify error logs capture exception information."""
    try:
        raise ValueError("Test error")
    except ValueError as e:
        json_logger.error(
            "Operation failed",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )

    handler = json_logger.handlers[0]
    stream = handler.stream  # type: ignore
    log_data = json.loads(stream.getvalue().strip())

    assert log_data["message"] == "Operation failed"
    assert log_data["error"] == "Test error"
    assert log_data["error_type"] == "ValueError"
    assert log_data["level"] == "ERROR"


def test_structured_logging_debug_level(json_logger: logging.Logger) -> None:
    """Verify debug level logs are captured."""
    json_logger.debug(
        "Debug information",
        extra={
            "operation": "git_pull",
            "duration_ms": 150,
        },
    )

    handler = json_logger.handlers[0]
    stream = handler.stream  # type: ignore
    log_data = json.loads(stream.getvalue().strip())

    assert log_data["level"] == "DEBUG"
    assert log_data["operation"] == "git_pull"
    assert log_data["duration_ms"] == 150


def test_structured_logging_warning_level(json_logger: logging.Logger) -> None:
    """Verify warning level logs are captured."""
    json_logger.warning(
        "Recoverable issue",
        extra={
            "issue": "title_generation_failed",
            "fallback_used": True,
        },
    )

    handler = json_logger.handlers[0]
    stream = handler.stream  # type: ignore
    log_data = json.loads(stream.getvalue().strip())

    assert log_data["level"] == "WARNING"
    assert log_data["issue"] == "title_generation_failed"
    assert log_data["fallback_used"] is True


def test_structured_logging_json_formatter_with_timestamp(json_logger: logging.Logger) -> None:
    """Verify JSON formatter includes timestamp."""
    json_logger.info("Timestamped log", extra={"event_id": "123"})

    handler = json_logger.handlers[0]
    stream = handler.stream  # type: ignore
    log_data = json.loads(stream.getvalue().strip())

    # Verify timestamp is present and is ISO format
    assert "timestamp" in log_data
    # ISO format: 2026-01-05T14:30:47.123Z
    assert "T" in log_data["timestamp"]
    assert "Z" in log_data["timestamp"]


def test_structured_logging_preserves_field_types(json_logger: logging.Logger) -> None:
    """Verify field types are preserved in JSON output."""
    json_logger.info(
        "Type test",
        extra={
            "string_field": "test",
            "int_field": 42,
            "float_field": 3.14,
            "bool_field": True,
            "null_field": None,
        },
    )

    handler = json_logger.handlers[0]
    stream = handler.stream  # type: ignore
    log_data = json.loads(stream.getvalue().strip())

    assert isinstance(log_data["string_field"], str)
    assert log_data["string_field"] == "test"
    assert isinstance(log_data["int_field"], int)
    assert log_data["int_field"] == 42
    assert isinstance(log_data["float_field"], float)
    assert log_data["float_field"] == 3.14
    assert isinstance(log_data["bool_field"], bool)
    assert log_data["bool_field"] is True
    assert log_data["null_field"] is None


def test_structured_logging_empty_extra_dict(json_logger: logging.Logger) -> None:
    """Verify logs work with empty extra dict."""
    json_logger.info("Simple log", extra={})

    handler = json_logger.handlers[0]
    stream = handler.stream  # type: ignore
    log_data = json.loads(stream.getvalue().strip())

    assert log_data["message"] == "Simple log"
    assert log_data["level"] == "INFO"


def test_structured_logging_special_characters(json_logger: logging.Logger) -> None:
    """Verify special characters are properly escaped in JSON."""
    json_logger.info(
        "Special chars",
        extra={
            "path": "/vault/Inbox/2025-12-21_14-30-00.md",
            "message": 'Contains "quotes" and \\ backslash',
            "unicode": "Unicode: 🚀 ✅ ⚠️",
        },
    )

    handler = json_logger.handlers[0]
    stream = handler.stream  # type: ignore
    log_data = json.loads(stream.getvalue().strip())

    assert log_data["path"] == "/vault/Inbox/2025-12-21_14-30-00.md"
    assert "quotes" in log_data["message"]
    assert "backslash" in log_data["message"]
    assert "🚀" in log_data["unicode"]
