"""
Service for managing command run state and output events.

Stores command execution state in memory with bounded event buffers
for HTTP polling-based output retrieval.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class RunStatus(str, Enum):
    """Status of a command run."""

    STARTED = "started"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class RunEvent:
    """Single event from a command run."""

    event_id: int
    type: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class CommandRun:
    """State for a single command run."""

    run_id: str
    command_name: str
    status: RunStatus
    started_at: datetime
    completed_at: datetime | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    error: str | None = None
    events: deque[RunEvent] = field(default_factory=lambda: deque(maxlen=200))
    next_event_id: int = 0
    dropped_before: int = 0
    task: asyncio.Task[None] | None = None


class CommandRunManager:
    """
    Manages command run lifecycle and event buffering.

    Stores run state in memory with bounded event buffers (max 200 events).
    Old events are evicted when buffer is full (FIFO policy).
    Runs expire after 60 minutes of inactivity.
    """

    def __init__(self, retention_minutes: int = 60, max_events_per_run: int = 200) -> None:
        """
        Initialize command run manager.

        Args:
            retention_minutes: How long to keep completed runs (default: 60)
            max_events_per_run: Maximum events per run buffer (default: 200)
        """
        self.retention_minutes = retention_minutes
        self.max_events_per_run = max_events_per_run
        self._runs: dict[str, CommandRun] = {}
        self._lock = asyncio.Lock()

    async def create_run(self, command_name: str) -> str:
        """
        Create a new command run.

        Args:
            command_name: Name of the command being executed

        Returns:
            Run ID for the new run
        """
        run_id = f"cmdrun_{uuid4().hex[:16]}"

        async with self._lock:
            self._runs[run_id] = CommandRun(
                run_id=run_id,
                command_name=command_name,
                status=RunStatus.STARTED,
                started_at=datetime.now(UTC),
                events=deque(maxlen=self.max_events_per_run),
            )

        logger.info(
            "Created command run",
            extra={
                "run_id": run_id,
                "command_name": command_name,
            },
        )

        return run_id

    async def update_status(
        self,
        run_id: str,
        status: RunStatus,
        *,
        error: str | None = None,
        cost_usd: float | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """
        Update run status and completion metadata.

        Args:
            run_id: Run identifier
            status: New status
            error: Error message (if status is ERROR)
            cost_usd: API cost in USD
            duration_ms: Duration in milliseconds
        """
        async with self._lock:
            run = self._runs.get(run_id)
            if not run:
                logger.warning(
                    "Attempted to update non-existent run",
                    extra={"run_id": run_id},
                )
                return

            run.status = status
            if status in (RunStatus.COMPLETED, RunStatus.ERROR):
                run.completed_at = datetime.now(UTC)
            if error:
                run.error = error
            if cost_usd is not None:
                run.cost_usd = cost_usd
            if duration_ms is not None:
                run.duration_ms = duration_ms

        logger.info(
            "Updated command run status",
            extra={
                "run_id": run_id,
                "status": status.value,
                "cost_usd": cost_usd,
                "duration_ms": duration_ms,
            },
        )

    async def append_event(self, run_id: str, event_type: str, data: dict[str, Any]) -> None:
        """
        Append event to run's event buffer.

        Args:
            run_id: Run identifier
            event_type: Event type (text, tool_use, thinking, complete, error)
            data: Event payload
        """
        async with self._lock:
            run = self._runs.get(run_id)
            if not run:
                logger.warning(
                    "Attempted to append event to non-existent run",
                    extra={"run_id": run_id},
                )
                return

            event_id = run.next_event_id
            run.next_event_id += 1

            # Check if buffer is full and will evict oldest event
            if len(run.events) == run.events.maxlen:
                run.dropped_before = run.events[0].event_id + 1

            run.events.append(RunEvent(event_id=event_id, type=event_type, data=data))

        logger.debug(
            "Appended event to run",
            extra={
                "run_id": run_id,
                "event_id": event_id,
                "event_type": event_type,
            },
        )

    async def get_run_status(
        self, run_id: str, after_event_id: int | None = None
    ) -> dict[str, Any] | None:
        """
        Get run status and events.

        Args:
            run_id: Run identifier
            after_event_id: Return only events after this ID (for polling)

        Returns:
            Dictionary with run status, events, and metadata, or None if run not found
        """
        async with self._lock:
            run = self._runs.get(run_id)
            if not run:
                return None

            # Filter events by cursor
            events = list(run.events)
            if after_event_id is not None:
                events = [e for e in events if e.event_id > after_event_id]

            # Build response; use -1 when no events exist to avoid skipping event_id=0.
            next_cursor = run.next_event_id - 1 if run.next_event_id > 0 else -1

            return {
                "run_id": run.run_id,
                "command_name": run.command_name,
                "status": run.status.value,
                "started_at": run.started_at.isoformat(),
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "cost_usd": run.cost_usd,
                "duration_ms": run.duration_ms,
                "error": run.error,
                "events": [
                    {
                        "event_id": e.event_id,
                        "type": e.type,
                        **e.data,
                    }
                    for e in events
                ],
                "next_cursor": next_cursor,
                "dropped_before": run.dropped_before,
            }

    async def set_task(self, run_id: str, task: asyncio.Task[None]) -> None:
        """
        Attach asyncio task to run for cancellation support.

        Args:
            run_id: Run identifier
            task: Asyncio task executing the command
        """
        async with self._lock:
            run = self._runs.get(run_id)
            if run:
                run.task = task

    async def cleanup_expired_runs(self) -> int:
        """
        Remove runs that have exceeded retention time.

        Returns:
            Number of runs removed
        """
        now = datetime.now(UTC)
        cutoff = now.timestamp() - (self.retention_minutes * 60)

        async with self._lock:
            expired = [
                run_id
                for run_id, run in self._runs.items()
                if (run.completed_at and run.completed_at.timestamp() < cutoff)
                or run.started_at.timestamp() < cutoff
            ]

            for run_id in expired:
                del self._runs[run_id]

        if expired:
            logger.info(
                "Cleaned up expired command runs",
                extra={
                    "count": len(expired),
                    "retention_minutes": self.retention_minutes,
                },
            )

        return len(expired)

    async def get_active_run_count(self) -> int:
        """Get count of active (non-completed) runs."""
        async with self._lock:
            return sum(
                1
                for run in self._runs.values()
                if run.status in (RunStatus.STARTED, RunStatus.RUNNING)
            )
