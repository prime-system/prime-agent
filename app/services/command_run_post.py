"""Post-run processing for command runs."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.exceptions import CommandRunPostError, GitError, VaultError
from app.models.command_run_log import CommandRunGitSummary, CommandRunSummary

if TYPE_CHECKING:
    from app.services.git import GitService
    from app.services.logs import LogService
    from app.services.vault import VaultService

logger = logging.getLogger(__name__)


def sync_command_run(
    *,
    command_name: str,
    run_id: str | None,
    status: str,
    scheduled: bool,
    duration_ms: int | None,
    duration_seconds: float | None,
    cost_usd: float | None,
    error: str | None,
    git_service: GitService,
    log_service: LogService,
    vault_service: VaultService,
) -> None:
    """Sync git and write logs after a command run."""
    timestamp = datetime.now(UTC)
    errors: list[Exception] = []

    pull_status = "skipped"
    pull_error: str | None = None
    changed_files_count = 0
    vault_commit_status = "skipped"
    vault_commit_hash: str | None = None
    vault_commit_error: str | None = None
    push_status = "skipped"
    push_error: str | None = None

    if git_service.enabled:
        try:
            git_service.pull()
            pull_status = "success"
        except GitError as e:
            pull_status = "failed"
            pull_error = str(e)
            errors.append(e)
            logger.exception(
                "Git pull failed after command run",
                extra={
                    "command_name": command_name,
                    "run_id": run_id,
                    **e.context,
                },
            )
        except Exception as e:
            pull_status = "failed"
            pull_error = str(e)
            errors.append(e)
            logger.exception(
                "Unexpected error during git pull after command run",
                extra={
                    "command_name": command_name,
                    "run_id": run_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )

        changed_files = git_service.get_changed_files()
        changed_files_count = len(changed_files)

        if changed_files:
            commit_message = _build_commit_message(
                prefix="Command",
                command_name=command_name,
                scheduled=scheduled,
                timestamp=timestamp,
                run_id=run_id,
            )
            try:
                git_service.commit(commit_message, changed_files)
                vault_commit_status = "committed"
                vault_commit_hash = git_service.get_head_commit_hash()
            except GitError as e:
                vault_commit_status = "failed"
                vault_commit_error = str(e)
                errors.append(e)
                logger.exception(
                    "Git commit failed after command run",
                    extra={
                        "command_name": command_name,
                        "run_id": run_id,
                        **e.context,
                    },
                )
            except Exception as e:
                vault_commit_status = "failed"
                vault_commit_error = str(e)
                errors.append(e)
                logger.exception(
                    "Unexpected error during git commit after command run",
                    extra={
                        "command_name": command_name,
                        "run_id": run_id,
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                )
        else:
            vault_commit_status = "skipped_no_changes"

        push_status = "pending"

    duration_seconds_value = duration_seconds
    if duration_seconds_value is None and duration_ms is not None:
        duration_seconds_value = duration_ms / 1000.0

    summary = CommandRunSummary(
        command_name=command_name,
        run_id=run_id,
        status=status,
        scheduled=scheduled,
        duration_seconds=duration_seconds_value,
        cost_usd=cost_usd,
        error=error,
        timestamp=timestamp,
    )
    git_summary = CommandRunGitSummary(
        enabled=git_service.enabled,
        pull_status=pull_status,
        pull_error=pull_error,
        changed_files_count=changed_files_count,
        vault_commit_status=vault_commit_status,
        vault_commit_hash=vault_commit_hash,
        vault_commit_error=vault_commit_error,
        push_status=push_status,
        push_error=push_error,
    )

    log_path = _write_command_run_log(
        log_service=log_service,
        vault_service=vault_service,
        summary=summary,
        git_summary=git_summary,
        errors=errors,
    )

    if git_service.enabled and log_path is not None:
        log_commit_message = _build_commit_message(
            prefix="Command log",
            command_name=command_name,
            scheduled=scheduled,
            timestamp=timestamp,
            run_id=run_id,
        )
        try:
            git_service.commit(log_commit_message, [log_path])
        except GitError as e:
            errors.append(e)
            logger.exception(
                "Git commit failed for command run log",
                extra={
                    "command_name": command_name,
                    "run_id": run_id,
                    **e.context,
                },
            )
        except Exception as e:
            errors.append(e)
            logger.exception(
                "Unexpected error committing command run log",
                extra={
                    "command_name": command_name,
                    "run_id": run_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )

    if git_service.enabled:
        try:
            git_service.push()
        except GitError as e:
            errors.append(e)
            logger.exception(
                "Git push failed after command run",
                extra={
                    "command_name": command_name,
                    "run_id": run_id,
                    **e.context,
                },
            )
        except Exception as e:
            errors.append(e)
            logger.exception(
                "Unexpected error during git push after command run",
                extra={
                    "command_name": command_name,
                    "run_id": run_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )

    if errors:
        message = "Post-run sync encountered errors"
        raise CommandRunPostError(
            message,
            context={
                "command_name": command_name,
                "run_id": run_id,
                "error_count": len(errors),
                "error_types": [type(err).__name__ for err in errors],
            },
        )


def _write_command_run_log(
    *,
    log_service: LogService,
    vault_service: VaultService,
    summary: CommandRunSummary,
    git_summary: CommandRunGitSummary,
    errors: list[Exception],
) -> str | None:
    try:
        log_path = log_service.create_command_run_log(summary, git_summary)
    except VaultError as e:
        errors.append(e)
        logger.exception(
            "Failed to write command run log",
            extra={
                "command_name": summary.command_name,
                "run_id": summary.run_id,
                **e.context,
            },
        )
        return None
    except Exception as e:
        errors.append(e)
        logger.exception(
            "Unexpected error writing command run log",
            extra={
                "command_name": summary.command_name,
                "run_id": summary.run_id,
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        return None

    if log_path.is_absolute():
        return vault_service.get_relative_path(log_path)
    return str(log_path)


def _build_commit_message(
    *,
    prefix: str,
    command_name: str,
    scheduled: bool,
    timestamp: datetime,
    run_id: str | None,
) -> str:
    scheduled_label = "scheduled" if scheduled else "manual"
    timestamp_label = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    message = f"{prefix}: {command_name} ({scheduled_label}) at {timestamp_label}"
    if run_id:
        message = f"{message} [run_id={run_id}]"
    return message
