from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.exceptions import CommandRunPostError, GitError
from app.services.command_run_post import sync_command_run
from app.services.git import GitService
from app.services.logs import LogService
from app.services.vault import VaultService


def _init_services(vault_path: Path) -> tuple[VaultService, LogService]:
    vault_service = VaultService(str(vault_path))
    vault_service.ensure_structure()
    log_service = LogService(
        logs_dir=vault_service.logs_path(),
        vault_path=vault_service.vault_path,
        vault_service=vault_service,
    )
    return vault_service, log_service


def test_command_run_log_written_manual(temp_vault: Path) -> None:
    vault_service, log_service = _init_services(temp_vault)
    git_service = GitService(vault_path=str(temp_vault), enabled=False)

    sync_command_run(
        command_name="dailyBrief",
        run_id="cmdrun_123",
        status="completed",
        scheduled=False,
        duration_ms=1200,
        duration_seconds=None,
        cost_usd=0.01,
        error=None,
        git_service=git_service,
        log_service=log_service,
        vault_service=vault_service,
    )

    log_files = list(vault_service.logs_path().glob("command-dailyBrief-*.md"))
    assert log_files, "Expected command run log file to be created"

    content = log_files[0].read_text(encoding="utf-8")
    assert "Command: dailyBrief" in content
    assert "Status: completed" in content
    assert "Outcome: skipped" in content


def test_command_run_git_sync_with_changes(temp_vault: Path) -> None:
    vault_service, log_service = _init_services(temp_vault)

    git_service = MagicMock(spec=GitService)
    git_service.enabled = True
    git_service.pull = MagicMock()
    git_service.get_changed_files.return_value = ["Notes/test.md"]
    git_service.commit = MagicMock()
    git_service.push = MagicMock()
    git_service.get_head_commit_hash.return_value = "abc123"

    sync_command_run(
        command_name="dailyBrief",
        run_id="cmdrun_456",
        status="completed",
        scheduled=True,
        duration_ms=500,
        duration_seconds=None,
        cost_usd=0.02,
        error=None,
        git_service=git_service,
        log_service=log_service,
        vault_service=vault_service,
    )

    git_service.pull.assert_called_once()
    assert git_service.commit.call_count == 2
    git_service.push.assert_called_once()

    first_message, first_paths = git_service.commit.call_args_list[0][0]
    assert "Command: dailyBrief" in first_message
    assert "(scheduled)" in first_message
    assert first_paths == ["Notes/test.md"]

    log_files = list(vault_service.logs_path().glob("command-dailyBrief-*.md"))
    assert len(log_files) == 1
    log_relative_path = vault_service.get_relative_path(log_files[0])

    second_message, second_paths = git_service.commit.call_args_list[1][0]
    assert "Command log: dailyBrief" in second_message
    assert "(scheduled)" in second_message
    assert second_paths == [log_relative_path]

    content = log_files[0].read_text(encoding="utf-8")
    assert "Changed Files: 1" in content


def test_git_disabled_skips_operations(temp_vault: Path) -> None:
    vault_service, log_service = _init_services(temp_vault)

    git_service = MagicMock(spec=GitService)
    git_service.enabled = False
    git_service.pull = MagicMock()
    git_service.commit = MagicMock()
    git_service.push = MagicMock()

    sync_command_run(
        command_name="dailyBrief",
        run_id=None,
        status="completed",
        scheduled=False,
        duration_ms=None,
        duration_seconds=1.5,
        cost_usd=None,
        error=None,
        git_service=git_service,
        log_service=log_service,
        vault_service=vault_service,
    )

    git_service.pull.assert_not_called()
    git_service.commit.assert_not_called()
    git_service.push.assert_not_called()

    log_files = list(vault_service.logs_path().glob("command-dailyBrief-*.md"))
    assert log_files, "Expected command run log file to be created"
    content = log_files[0].read_text(encoding="utf-8")
    assert "Outcome: skipped" in content


def test_git_failure_still_writes_log(temp_vault: Path) -> None:
    vault_service, log_service = _init_services(temp_vault)

    git_service = MagicMock(spec=GitService)
    git_service.enabled = True
    git_service.pull.side_effect = GitError(
        "Pull failed",
        context={"operation": "pull", "vault_path": str(temp_vault)},
    )
    git_service.get_changed_files.return_value = []
    git_service.commit = MagicMock()
    git_service.push = MagicMock()

    with pytest.raises(CommandRunPostError):
        sync_command_run(
            command_name="dailyBrief",
            run_id="cmdrun_789",
            status="error",
            scheduled=False,
            duration_ms=None,
            duration_seconds=2.0,
            cost_usd=None,
            error="Agent failed",
            git_service=git_service,
            log_service=log_service,
            vault_service=vault_service,
        )

    log_files = list(vault_service.logs_path().glob("command-dailyBrief-*.md"))
    assert log_files, "Expected command run log file to be created even on git failure"


def test_log_service_refreshes_logs_folder_from_settings(temp_vault: Path) -> None:
    vault_service, log_service = _init_services(temp_vault)

    settings_path = temp_vault / ".prime" / "settings.yaml"
    settings_path.write_text("logs:\n  folder: CustomLogs\n", encoding="utf-8")

    log_path = log_service.create_run_log(duration_seconds=0.5)
    assert log_path.parts[0] == "CustomLogs"

    created_log = temp_vault / log_path
    assert created_log.exists()
