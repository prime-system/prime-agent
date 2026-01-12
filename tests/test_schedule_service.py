"""Tests for schedule service overlap handling."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.command import CommandInfo, CommandListResponse, CommandType
from app.models.schedule_config import ScheduleJobConfig
from app.services.schedule import ScheduleJobState, ScheduleService


@pytest.fixture
def schedule_service(temp_vault: Path) -> ScheduleService:
    """Create a schedule service with mocked dependencies."""
    agent_service = MagicMock()
    agent_service.run_command = AsyncMock(
        return_value={
            "success": True,
            "cost_usd": 0.0,
            "duration_ms": 10,
            "error": None,
        }
    )
    command_service = MagicMock()
    command_service.list_commands.return_value = CommandListResponse(
        commands=[
            CommandInfo(
                name="dailyBrief",
                description="Daily brief",
                type=CommandType.VAULT,
                namespace=None,
                argument_hint=None,
                path=".claude/commands/dailyBrief.md",
                file_name="dailyBrief.md",
            )
        ],
        total=1,
        vault_commands=1,
        plugin_commands=0,
        mcp_commands=0,
    )

    return ScheduleService(
        vault_path=str(temp_vault),
        agent_service=agent_service,
        command_service=command_service,
    )


@pytest.mark.asyncio
async def test_queue_max_drops_newer_runs(schedule_service: ScheduleService) -> None:
    """Queue mode with queue_max=1 drops newer runs."""
    job_config = ScheduleJobConfig(
        id="daily-brief",
        command="dailyBrief",
        cron="*/5 * * * *",
        overlap="queue",
        queue_max=1,
    )
    state = ScheduleJobState(config=job_config)
    state.running_task = asyncio.create_task(asyncio.sleep(10))

    now = schedule_service._now()
    await schedule_service._trigger_job(state, now)
    assert state.queued_runs == 1
    assert state.skipped_runs == 0

    await schedule_service._trigger_job(state, now)
    assert state.queued_runs == 1
    assert state.skipped_runs == 1

    state.running_task.cancel()
    with suppress(asyncio.CancelledError):
        await state.running_task


@pytest.mark.asyncio
async def test_skip_mode_skips_when_running(schedule_service: ScheduleService) -> None:
    """Skip mode ignores overlaps when already running."""
    job_config = ScheduleJobConfig(
        id="daily-brief",
        command="dailyBrief",
        cron="*/5 * * * *",
        overlap="skip",
    )
    state = ScheduleJobState(config=job_config)
    state.running_task = asyncio.create_task(asyncio.sleep(10))

    now = schedule_service._now()
    await schedule_service._trigger_job(state, now)
    assert state.queued_runs == 0
    assert state.skipped_runs == 1

    state.running_task.cancel()
    with suppress(asyncio.CancelledError):
        await state.running_task
