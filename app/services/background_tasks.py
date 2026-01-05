"""Background task utilities with error tracking.

Provides safe wrappers for background tasks that ensure exceptions
are logged and tracked, preventing silent failures.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)


class BackgroundTaskError:
    """Record of a failed background task."""

    def __init__(
        self,
        task_name: str,
        error: Exception,
        timestamp: datetime | None = None,
    ):
        self.task_name = task_name
        self.error = error
        self.timestamp = timestamp or datetime.utcnow()
        self.error_type = type(error).__name__
        self.error_message = str(error)


class BackgroundTaskTracker:
    """Track background task results for monitoring."""

    def __init__(self, max_history: int = 100):
        self.max_history = max_history
        self.successful_tasks: list[tuple[str, datetime]] = []
        self.failed_tasks: list[BackgroundTaskError] = []
        self._lock = asyncio.Lock()

    async def record_success(self, task_name: str) -> None:
        """Record successful task completion."""
        async with self._lock:
            self.successful_tasks.append((task_name, datetime.utcnow()))
            if len(self.successful_tasks) > self.max_history:
                self.successful_tasks = self.successful_tasks[-self.max_history :]

    async def record_failure(self, task_name: str, error: Exception) -> None:
        """Record failed task."""
        task_error = BackgroundTaskError(task_name, error)
        async with self._lock:
            self.failed_tasks.append(task_error)
            if len(self.failed_tasks) > self.max_history:
                self.failed_tasks = self.failed_tasks[-self.max_history :]

        # Also log immediately
        logger.error(
            "Background task failed: %s - %s",
            task_error.task_name,
            task_error.error_message,
            exc_info=error,
            extra={"task_name": task_name, "error_type": task_error.error_type},
        )

    async def get_status(self) -> dict[str, Any]:
        """Get current status of background tasks."""
        async with self._lock:
            return {
                "successful_tasks": len(self.successful_tasks),
                "failed_tasks": len(self.failed_tasks),
                "recent_failures": [
                    {
                        "task": f.task_name,
                        "error": f.error_message,
                        "type": f.error_type,
                        "timestamp": f.timestamp.isoformat(),
                    }
                    for f in self.failed_tasks[-5:]  # Last 5 failures
                ],
            }


_task_tracker: BackgroundTaskTracker | None = None


def get_task_tracker() -> BackgroundTaskTracker:
    """Get or create the global task tracker."""
    global _task_tracker
    if _task_tracker is None:
        _task_tracker = BackgroundTaskTracker()
    return _task_tracker


async def safe_background_task(
    task_name: str, coro: Callable[[], Any]
) -> None:
    """
    Execute a background task safely, logging any errors.

    This wrapper ensures that:
    - All exceptions are logged with context
    - Task results are tracked for monitoring
    - Errors don't silently disappear

    Args:
        task_name: Name of the task for logging/tracking
        coro: Callable to execute (can be sync or async)
    """
    tracker = get_task_tracker()

    try:
        logger.debug(
            "Starting background task",
            extra={"task_name": task_name},
        )

        if asyncio.iscoroutinefunction(coro):
            await coro()
        else:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, coro)

        logger.info(
            "Background task completed",
            extra={"task_name": task_name},
        )
        await tracker.record_success(task_name)

    except Exception as e:
        logger.error(
            "Background task failed",
            exc_info=True,
            extra={
                "task_name": task_name,
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        await tracker.record_failure(task_name, e)
