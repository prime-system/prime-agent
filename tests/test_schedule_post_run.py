from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.command import CommandInfo, CommandListResponse, CommandType
from app.models.schedule_config import ScheduleJobConfig
from app.services.schedule import ScheduleJobState, ScheduleService


@pytest.mark.asyncio
async def test_schedule_triggers_post_run_helper(temp_vault, monkeypatch) -> None:
    agent_service = MagicMock()
    agent_service.run_command = AsyncMock(
        return_value={
            "success": True,
            "cost_usd": 0.0,
            "duration_ms": 5,
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

    schedule_service = ScheduleService(
        vault_path=str(temp_vault),
        agent_service=agent_service,
        command_service=command_service,
        chat_title_service=MagicMock(),
        git_service=MagicMock(),
        log_service=MagicMock(),
        vault_service=MagicMock(),
    )

    captured: dict[str, object] = {}

    def fake_sync_command_run(**kwargs) -> None:
        captured.update(kwargs)

    async def fake_safe_background_task(task_name: str, func) -> None:
        func()
        captured["task_name"] = task_name

    monkeypatch.setattr("app.services.schedule.sync_command_run", fake_sync_command_run)
    monkeypatch.setattr("app.services.schedule.safe_background_task", fake_safe_background_task)

    job_config = ScheduleJobConfig(
        id="daily-brief",
        command="dailyBrief",
        cron="*/5 * * * *",
        overlap="skip",
    )
    state = ScheduleJobState(config=job_config)

    await schedule_service._run_job(state)
    await asyncio.sleep(0)

    assert captured["command_name"] == "dailyBrief"
    assert captured["scheduled"] is True
    assert captured["status"] == "success"
