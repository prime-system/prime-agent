"""Models for command run audit logs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True)
class CommandRunSummary:
    """Summary details for a command run log."""

    command_name: str
    run_id: str | None
    status: str
    scheduled: bool
    duration_seconds: float | None
    cost_usd: float | None
    error: str | None
    timestamp: datetime


@dataclass(frozen=True)
class CommandRunGitSummary:
    """Git sync details for a command run log."""

    enabled: bool
    pull_status: str
    pull_error: str | None
    changed_files_count: int
    vault_commit_status: str
    vault_commit_hash: str | None
    vault_commit_error: str | None
    push_status: str
    push_error: str | None
