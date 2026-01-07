"""Tests for background task error tracking."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from app.services.background_tasks import (
    BackgroundTaskError,
    BackgroundTaskTracker,
    safe_background_task,
    get_task_tracker,
)


class TestBackgroundTaskError:
    """Test BackgroundTaskError record."""

    def test_error_creation(self) -> None:
        """Verify error record stores exception details."""
        error = ValueError("Test error message")
        task_error = BackgroundTaskError("test_task", error)

        assert task_error.task_name == "test_task"
        assert task_error.error is error
        assert task_error.error_type == "ValueError"
        assert task_error.error_message == "Test error message"
        assert isinstance(task_error.timestamp, datetime)

    def test_error_with_custom_timestamp(self) -> None:
        """Verify custom timestamp can be provided."""
        custom_time = datetime(2025, 1, 1, 12, 0, 0)
        error = ValueError("Test")
        task_error = BackgroundTaskError("task", error, custom_time)

        assert task_error.timestamp == custom_time


class TestBackgroundTaskTracker:
    """Test BackgroundTaskTracker functionality."""

    @pytest.mark.asyncio
    async def test_successful_task_tracking(self) -> None:
        """Verify successful tasks are tracked."""
        tracker = BackgroundTaskTracker()

        await tracker.record_success("task_1")
        await tracker.record_success("task_2")

        status = await tracker.get_status()
        assert status["successful_tasks"] == 2
        assert status["failed_tasks"] == 0
        assert status["recent_failures"] == []

    @pytest.mark.asyncio
    async def test_failed_task_tracking(self) -> None:
        """Verify failed tasks are tracked with error details."""
        tracker = BackgroundTaskTracker()

        error = RuntimeError("Something went wrong")
        await tracker.record_failure("failing_task", error)

        status = await tracker.get_status()
        assert status["failed_tasks"] == 1
        assert len(status["recent_failures"]) == 1

        failure = status["recent_failures"][0]
        assert failure["task"] == "failing_task"
        assert failure["error"] == "Something went wrong"
        assert failure["type"] == "RuntimeError"
        assert "timestamp" in failure

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure(self) -> None:
        """Verify tracker handles both successes and failures."""
        tracker = BackgroundTaskTracker()

        await tracker.record_success("task_1")
        await tracker.record_failure("task_2", ValueError("Error 1"))
        await tracker.record_success("task_3")
        await tracker.record_failure("task_4", RuntimeError("Error 2"))

        status = await tracker.get_status()
        assert status["successful_tasks"] == 2
        assert status["failed_tasks"] == 2
        assert len(status["recent_failures"]) == 2

    @pytest.mark.asyncio
    async def test_history_limit(self) -> None:
        """Verify tracker maintains max history size."""
        tracker = BackgroundTaskTracker(max_history=5)

        # Record more than max_history items
        for i in range(10):
            await tracker.record_success(f"task_{i}")

        status = await tracker.get_status()
        assert status["successful_tasks"] == 5  # Only last 5 kept

    @pytest.mark.asyncio
    async def test_recent_failures_limit(self) -> None:
        """Verify only last 5 failures are returned."""
        tracker = BackgroundTaskTracker(max_history=100)

        # Record 10 failures
        for i in range(10):
            await tracker.record_failure(f"task_{i}", ValueError(f"Error {i}"))

        status = await tracker.get_status()
        assert status["failed_tasks"] == 10
        assert len(status["recent_failures"]) == 5  # Only last 5

        # Verify it's the most recent failures
        recent_task_names = [f["task"] for f in status["recent_failures"]]
        assert "task_9" in recent_task_names
        assert "task_5" in recent_task_names
        assert "task_4" not in recent_task_names

    @pytest.mark.asyncio
    async def test_concurrent_access(self) -> None:
        """Verify tracker is thread-safe with concurrent access."""
        tracker = BackgroundTaskTracker()

        async def record_tasks(count: int) -> None:
            for i in range(count):
                await tracker.record_success(f"task_{i}")

        # Run concurrent operations
        await asyncio.gather(
            record_tasks(10),
            record_tasks(10),
            record_tasks(10),
        )

        status = await tracker.get_status()
        assert status["successful_tasks"] == 30


class TestSafeBackgroundTask:
    """Test safe_background_task wrapper."""

    @pytest.mark.asyncio
    async def test_successful_async_task(self) -> None:
        """Verify successful async task is tracked."""
        tracker = BackgroundTaskTracker()

        call_count = 0

        async def async_task() -> None:
            nonlocal call_count
            call_count += 1

        # Use global tracker for this test
        import app.services.background_tasks as bg_module

        original_tracker = bg_module._task_tracker
        try:
            bg_module._task_tracker = tracker
            await safe_background_task("test_task", async_task)
        finally:
            bg_module._task_tracker = original_tracker

        assert call_count == 1
        status = await tracker.get_status()
        assert status["successful_tasks"] == 1
        assert status["failed_tasks"] == 0

    @pytest.mark.asyncio
    async def test_successful_sync_task(self) -> None:
        """Verify successful sync task is tracked."""
        tracker = BackgroundTaskTracker()

        call_count = 0

        def sync_task() -> None:
            nonlocal call_count
            call_count += 1

        # Use global tracker for this test
        import app.services.background_tasks as bg_module

        original_tracker = bg_module._task_tracker
        try:
            bg_module._task_tracker = tracker
            await safe_background_task("test_task", sync_task)
        finally:
            bg_module._task_tracker = original_tracker

        assert call_count == 1
        status = await tracker.get_status()
        assert status["successful_tasks"] == 1
        assert status["failed_tasks"] == 0

    @pytest.mark.asyncio
    async def test_failed_async_task(self) -> None:
        """Verify failed async task is tracked."""
        tracker = BackgroundTaskTracker()

        async def failing_task() -> None:
            raise ValueError("Task failed!")

        # Use global tracker for this test
        import app.services.background_tasks as bg_module

        original_tracker = bg_module._task_tracker
        try:
            bg_module._task_tracker = tracker
            await safe_background_task("failing_task", failing_task)
        finally:
            bg_module._task_tracker = original_tracker

        status = await tracker.get_status()
        assert status["successful_tasks"] == 0
        assert status["failed_tasks"] == 1
        assert status["recent_failures"][0]["error"] == "Task failed!"

    @pytest.mark.asyncio
    async def test_failed_sync_task(self) -> None:
        """Verify failed sync task is tracked."""
        tracker = BackgroundTaskTracker()

        def failing_task() -> None:
            raise RuntimeError("Sync task failed!")

        # Use global tracker for this test
        import app.services.background_tasks as bg_module

        original_tracker = bg_module._task_tracker
        try:
            bg_module._task_tracker = tracker
            await safe_background_task("failing_task", failing_task)
        finally:
            bg_module._task_tracker = original_tracker

        status = await tracker.get_status()
        assert status["successful_tasks"] == 0
        assert status["failed_tasks"] == 1
        assert status["recent_failures"][0]["error"] == "Sync task failed!"

    @pytest.mark.asyncio
    async def test_task_doesnt_raise_to_caller(self) -> None:
        """Verify exceptions are caught and don't propagate."""

        async def failing_task() -> None:
            raise ValueError("This should be caught")

        # Should not raise
        await safe_background_task("task", failing_task)


class TestGetTaskTracker:
    """Test get_task_tracker global function."""

    def test_tracker_singleton(self) -> None:
        """Verify get_task_tracker returns same instance."""
        import app.services.background_tasks as bg_module

        # Reset the global tracker
        original_tracker = bg_module._task_tracker
        bg_module._task_tracker = None

        try:
            tracker1 = get_task_tracker()
            tracker2 = get_task_tracker()

            assert tracker1 is tracker2
        finally:
            bg_module._task_tracker = original_tracker
