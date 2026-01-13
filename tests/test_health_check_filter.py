"""Tests for health check log filtering."""

from __future__ import annotations

import logging

import pytest

from app.logging_config import HealthCheckFilter


class FakeLogRecord:
    """Mock log record for testing."""

    def __init__(self, message: str):
        self.message = message

    def getMessage(self) -> str:  # noqa: N802 - matches logging.LogRecord API
        """Return the log message."""
        return self.message


@pytest.fixture
def health_filter() -> HealthCheckFilter:
    """Create a health check filter instance."""
    return HealthCheckFilter()


def test_filter_suppresses_successful_health_checks(
    health_filter: HealthCheckFilter,
) -> None:
    """Test that successful (200) health checks are filtered out."""
    # Simulate uvicorn access log format
    successful_logs = [
        '127.0.0.1:56789 - "GET /health HTTP/1.1" 200 OK',
        '127.0.0.1:56789 - "GET /health/ready HTTP/1.1" 200 OK',
        '127.0.0.1:56789 - "GET /health/detailed HTTP/1.1" 200 OK',
    ]

    for log_message in successful_logs:
        record = FakeLogRecord(log_message)
        assert not health_filter.filter(record), f"Should filter: {log_message}"


def test_filter_allows_health_check_errors(health_filter: HealthCheckFilter) -> None:
    """Test that health check errors (4xx, 5xx) are NOT filtered."""
    error_logs = [
        '127.0.0.1:56789 - "GET /health HTTP/1.1" 500 Internal Server Error',
        '127.0.0.1:56789 - "GET /health/ready HTTP/1.1" 503 Service Unavailable',
        '127.0.0.1:56789 - "GET /health/detailed HTTP/1.1" 401 Unauthorized',
    ]

    for log_message in error_logs:
        record = FakeLogRecord(log_message)
        assert health_filter.filter(record), f"Should NOT filter: {log_message}"


def test_filter_allows_non_health_endpoints(health_filter: HealthCheckFilter) -> None:
    """Test that other endpoints are not filtered."""
    other_logs = [
        '127.0.0.1:56789 - "POST /api/v1/capture HTTP/1.1" 200 OK',
        '127.0.0.1:56789 - "GET /api/v1/commands HTTP/1.1" 200 OK',
        '127.0.0.1:56789 - "POST /api/v1/commands/test/trigger HTTP/1.1" 500 Internal Server Error',
    ]

    for log_message in other_logs:
        record = FakeLogRecord(log_message)
        assert health_filter.filter(record), f"Should NOT filter: {log_message}"


def test_filter_with_real_log_record(health_filter: HealthCheckFilter) -> None:
    """Test with a real logging.LogRecord instance."""
    logger = logging.getLogger("test")

    # Create a real log record
    record = logger.makeRecord(
        name="uvicorn.access",
        level=logging.INFO,
        fn="",
        lno=0,
        msg='127.0.0.1:56789 - "GET /health HTTP/1.1" 200 OK',
        args=(),
        exc_info=None,
    )

    assert not health_filter.filter(record), "Should filter successful health check"

    # Test with error
    error_record = logger.makeRecord(
        name="uvicorn.access",
        level=logging.ERROR,
        fn="",
        lno=0,
        msg='127.0.0.1:56789 - "GET /health HTTP/1.1" 503 Service Unavailable',
        args=(),
        exc_info=None,
    )

    assert health_filter.filter(error_record), "Should NOT filter health check errors"
