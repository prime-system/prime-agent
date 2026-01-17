"""Schedule service for running slash commands via .prime/schedule.yaml."""

from __future__ import annotations

import asyncio
import functools
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from zoneinfo import ZoneInfo

from croniter import croniter

from app.models.schedule import ScheduleJobStatus, ScheduleStatusResponse
from app.models.schedule_config import ScheduleConfig, ScheduleJobConfig, load_schedule_config
from app.services.background_tasks import safe_background_task
from app.services.command_run_post import sync_command_run
from app.services.lock import get_vault_lock
from app.utils.command_titles import format_command_title

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.services.agent import AgentService, ProcessResult
    from app.services.chat_titles import ChatTitleService
    from app.services.command import CommandService
    from app.services.git import GitService
    from app.services.logs import LogService
    from app.services.vault import VaultService


@dataclass
class ScheduleJobState:
    """In-memory state for a scheduled job."""

    config: ScheduleJobConfig
    next_run: datetime | None = None
    last_scheduled_at: datetime | None = None
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_status: str | None = None
    last_error: str | None = None
    last_cost_usd: float | None = None
    last_duration_ms: int | None = None
    running_task: asyncio.Task[None] | None = None
    queued_runs: int = 0
    skipped_runs: int = 0
    total_runs: int = 0
    total_failures: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


class ScheduleService:
    """Run scheduled slash commands from .prime/schedule.yaml."""

    def __init__(
        self,
        vault_path: str,
        agent_service: AgentService,
        command_service: CommandService,
        *,
        tick_seconds: int = 30,
        chat_title_service: ChatTitleService | None = None,
        git_service: GitService | None = None,
        log_service: LogService | None = None,
        vault_service: VaultService | None = None,
    ) -> None:
        self._vault_path = Path(vault_path)
        self._config_path = self._vault_path / ".prime" / "schedule.yaml"
        self._agent_service = agent_service
        self._command_service = command_service
        self._tick_seconds = tick_seconds
        self._chat_title_service = chat_title_service
        self._git_service = git_service
        self._log_service = log_service
        self._vault_service = vault_service

        self._timezone = ZoneInfo("UTC")
        self._config: ScheduleConfig = ScheduleConfig()
        self._config_error: str | None = None
        self._last_mtime: float | None = None

        self._jobs: dict[str, ScheduleJobState] = {}
        self._lock = asyncio.Lock()
        self._loop_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start schedule loop."""
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._run_loop())
            logger.info("Schedule loop started", extra={"config_path": str(self._config_path)})

    async def stop(self) -> None:
        """Stop schedule loop and cancel running jobs."""
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            logger.info("Schedule loop stopped")

        await self._cancel_all_jobs(reason="shutdown")

    async def get_status(self) -> ScheduleStatusResponse:
        """Return current schedule status for monitoring."""
        async with self._lock:
            states = list(self._jobs.values())
            timezone = self._timezone.key
            config_path = str(self._config_path)
            config_error = self._config_error

        jobs_status: list[ScheduleJobStatus] = []
        now = self._now()
        for state in states:
            async with state.lock:
                running = state.running_task is not None and not state.running_task.done()
                elapsed_seconds = None
                if running and state.last_started_at:
                    elapsed_seconds = (now - state.last_started_at).total_seconds()

                jobs_status.append(
                    ScheduleJobStatus(
                        id=state.config.id,
                        command=state.config.command,
                        arguments=state.config.arguments,
                        cron=state.config.cron,
                        enabled=state.config.enabled,
                        overlap=state.config.overlap,
                        queue_max=state.config.queue_max,
                        queued_runs=state.queued_runs,
                        skipped_runs=state.skipped_runs,
                        is_running=running,
                        started_at=state.last_started_at,
                        elapsed_seconds=elapsed_seconds,
                        last_finished_at=state.last_finished_at,
                        last_status=state.last_status,
                        last_error=state.last_error,
                        last_cost_usd=state.last_cost_usd,
                        last_duration_ms=state.last_duration_ms,
                        next_run=state.next_run,
                        timeout_seconds=state.config.timeout_seconds,
                        max_budget_usd=state.config.max_budget_usd,
                        model=state.config.model,
                        use_vault_lock=state.config.use_vault_lock,
                    )
                )

        return ScheduleStatusResponse(
            timezone=timezone,
            config_path=config_path,
            config_error=config_error,
            jobs=jobs_status,
        )

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job by id.

        Returns True if a running job was cancelled, False otherwise.
        """
        async with self._lock:
            state = self._jobs.get(job_id)

        if state is None:
            return False

        async with state.lock:
            task = state.running_task
            state.queued_runs = 0

        if task is None or task.done():
            return False

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        return True

    async def has_job(self, job_id: str) -> bool:
        """Check if a job exists."""
        async with self._lock:
            return job_id in self._jobs

    async def _run_loop(self) -> None:
        """Main scheduler loop."""
        while True:
            try:
                await self._maybe_reload_config()
                await self._process_due_jobs()
                await asyncio.sleep(self._tick_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(
                    "Schedule loop error",
                    extra={
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                )
                await asyncio.sleep(self._tick_seconds)

    async def _maybe_reload_config(self) -> None:
        if not self._should_reload_config():
            return

        try:
            new_config = load_schedule_config(self._vault_path)
        except Exception as e:
            self._config_error = str(e)
            logger.warning(
                "Failed to reload schedule config",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "config_path": str(self._config_path),
                },
            )
            if self._config_path.exists():
                self._last_mtime = self._config_path.stat().st_mtime
            return

        self._config_error = None
        self._config = new_config
        self._timezone = ZoneInfo(new_config.timezone)
        await self._sync_jobs(new_config.jobs)

        if self._config_path.exists():
            self._last_mtime = self._config_path.stat().st_mtime
        else:
            self._last_mtime = None

        logger.info(
            "Schedule config reloaded",
            extra={
                "config_path": str(self._config_path),
                "job_count": len(new_config.jobs),
            },
        )

    def _should_reload_config(self) -> bool:
        file_exists = self._config_path.exists()

        if self._last_mtime is None:
            return file_exists

        if not file_exists:
            return True

        current_mtime = self._config_path.stat().st_mtime
        return current_mtime != self._last_mtime

    async def _sync_jobs(self, jobs: list[ScheduleJobConfig]) -> None:
        job_ids = {job.id for job in jobs}
        now = self._now()

        async with self._lock:
            existing_ids = set(self._jobs.keys())

        removed_ids = existing_ids - job_ids
        for job_id in removed_ids:
            await self._cancel_job_internal(job_id, reason="removed")
            async with self._lock:
                self._jobs.pop(job_id, None)

        for job_config in jobs:
            async with self._lock:
                state = self._jobs.get(job_config.id)

            if state is None:
                state = ScheduleJobState(config=job_config)
                state.next_run = self._compute_next_run(job_config, now)
                async with self._lock:
                    self._jobs[job_config.id] = state
                continue

            async with state.lock:
                previous_cron = state.config.cron
                previous_enabled = state.config.enabled
                state.config = job_config

                if job_config.cron != previous_cron or job_config.enabled != previous_enabled:
                    state.next_run = self._compute_next_run(job_config, now)

    async def _process_due_jobs(self) -> None:
        async with self._lock:
            states = list(self._jobs.values())

        now = self._now()
        for state in states:
            await self._process_state_due(state, now)

    async def _process_state_due(self, state: ScheduleJobState, now: datetime) -> None:
        while True:
            async with state.lock:
                if not state.config.enabled:
                    return

                if state.next_run is None or state.next_run > now:
                    return

                scheduled_time = state.next_run
                state.last_scheduled_at = scheduled_time
                state.next_run = self._compute_next_run(state.config, scheduled_time)

            await self._trigger_job(state, scheduled_time)

    async def _trigger_job(self, state: ScheduleJobState, scheduled_time: datetime) -> None:
        async with state.lock:
            running = state.running_task is not None and not state.running_task.done()

            if running:
                if state.config.overlap == "skip":
                    state.skipped_runs += 1
                    logger.info(
                        "Scheduled job skipped (already running)",
                        extra={"job_id": state.config.id, "scheduled_time": scheduled_time},
                    )
                    return

                if state.config.queue_max == 0 or state.queued_runs >= state.config.queue_max:
                    state.skipped_runs += 1
                    logger.info(
                        "Scheduled job skipped (queue full)",
                        extra={
                            "job_id": state.config.id,
                            "queue_max": state.config.queue_max,
                            "scheduled_time": scheduled_time,
                        },
                    )
                    return

                state.queued_runs += 1
                logger.info(
                    "Scheduled job queued",
                    extra={
                        "job_id": state.config.id,
                        "queued_runs": state.queued_runs,
                        "scheduled_time": scheduled_time,
                    },
                )
                return

            state.running_task = asyncio.create_task(self._run_job(state))

    async def _run_job(self, state: ScheduleJobState) -> None:
        start_time = self._now()
        result: ProcessResult | None = None
        error_msg: str | None = None
        status = "success"

        async with state.lock:
            state.last_started_at = start_time
            state.total_runs += 1

        try:
            if not await self._command_exists(state.config.command):
                error_msg = f"Command not found: {state.config.command}"
                status = "error"
                logger.warning(
                    "Scheduled command not found",
                    extra={"job_id": state.config.id, "command": state.config.command},
                )
            else:
                if state.config.use_vault_lock:
                    vault_lock = get_vault_lock()
                    async with vault_lock:
                        result = await self._execute_command(state)
                else:
                    result = await self._execute_command(state)

                if result and not result.get("success"):
                    status = "error"
                    error_msg = result.get("error")
        except asyncio.CancelledError:
            status = "cancelled"
            error_msg = "Cancelled"
        except Exception as e:
            status = "error"
            error_msg = str(e)
            logger.exception(
                "Scheduled job failed",
                extra={
                    "job_id": state.config.id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
        finally:
            end_time = self._now()
            async with state.lock:
                state.running_task = None
                state.last_finished_at = end_time
                state.last_status = status
                state.last_error = error_msg
                if result is not None:
                    state.last_cost_usd = result.get("cost_usd")
                    state.last_duration_ms = result.get("duration_ms")
                else:
                    state.last_cost_usd = None
                    state.last_duration_ms = None

                if status != "success":
                    state.total_failures += 1

            duration_seconds = (end_time - start_time).total_seconds()
            self._schedule_post_run_sync(
                command_name=state.config.command,
                status=status,
                duration_ms=result.get("duration_ms") if result else None,
                duration_seconds=duration_seconds,
                cost_usd=result.get("cost_usd") if result else None,
                error=error_msg,
            )

            await self._maybe_run_queued(state)

    async def _execute_command(self, state: ScheduleJobState) -> ProcessResult:
        event_handler = None
        chat_title_service = self._chat_title_service
        if chat_title_service is not None:

            async def event_handler(event_type: str, data: dict[str, Any]) -> None:
                if event_type != "session_id":
                    return
                session_id = data.get("session_id") or data.get("sessionId")
                if not isinstance(session_id, str) or not session_id:
                    return
                if await chat_title_service.title_exists(session_id):
                    return
                title = format_command_title(state.config.command)
                created_at = datetime.now(UTC).isoformat()
                await chat_title_service.set_title(
                    session_id,
                    title,
                    created_at,
                    source="command",
                )

        return await self._agent_service.run_command(
            state.config.command,
            arguments=state.config.arguments,
            max_budget_usd=state.config.max_budget_usd,
            timeout_seconds=state.config.timeout_seconds,
            model=state.config.model,
            event_handler=event_handler,
        )

    async def _maybe_run_queued(self, state: ScheduleJobState) -> None:
        async with state.lock:
            if not state.config.enabled:
                state.queued_runs = 0
                return
            if state.queued_runs <= 0:
                return
            state.queued_runs -= 1
            state.running_task = asyncio.create_task(self._run_job(state))
            logger.info(
                "Scheduled job dequeued",
                extra={"job_id": state.config.id, "queued_runs": state.queued_runs},
            )

    async def _cancel_job_internal(self, job_id: str, *, reason: str) -> None:
        async with self._lock:
            state = self._jobs.get(job_id)

        if state is None:
            return

        async with state.lock:
            task = state.running_task
            state.queued_runs = 0

        if task is None or task.done():
            return

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        logger.info("Scheduled job cancelled", extra={"job_id": job_id, "reason": reason})

    async def _cancel_all_jobs(self, *, reason: str) -> None:
        async with self._lock:
            job_ids = list(self._jobs.keys())

        for job_id in job_ids:
            await self._cancel_job_internal(job_id, reason=reason)

    async def _command_exists(self, command_name: str) -> bool:
        try:
            commands = self._command_service.list_commands().commands
        except Exception as e:
            logger.warning(
                "Failed to list commands",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            return True

        for command in commands:
            full_name = f"{command.namespace}:{command.name}" if command.namespace else command.name
            if full_name == command_name:
                return True

        return False

    def _compute_next_run(self, job: ScheduleJobConfig, base_time: datetime) -> datetime | None:
        if not job.enabled:
            return None

        iterator = croniter(job.cron, base_time)
        return cast("datetime", iterator.get_next(datetime))

    def _now(self) -> datetime:
        return datetime.now(self._timezone)

    def _schedule_post_run_sync(
        self,
        *,
        command_name: str,
        status: str,
        duration_ms: int | None,
        duration_seconds: float | None,
        cost_usd: float | None,
        error: str | None,
    ) -> None:
        if self._git_service is None or self._log_service is None or self._vault_service is None:
            return

        post_run_task = functools.partial(
            sync_command_run,
            command_name=command_name,
            run_id=None,
            status=status,
            scheduled=True,
            duration_ms=duration_ms,
            duration_seconds=duration_seconds,
            cost_usd=cost_usd,
            error=error,
            git_service=self._git_service,
            log_service=self._log_service,
            vault_service=self._vault_service,
        )
        task_name = f"command_post_run:{command_name}"
        asyncio.create_task(safe_background_task(task_name, post_run_task))
