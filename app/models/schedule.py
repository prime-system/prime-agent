"""Models for schedule status and control responses."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import Literal

from pydantic import BaseModel, Field


class ScheduleJobStatus(BaseModel):
    """Runtime status for a scheduled job."""

    id: str = Field(..., description="Job identifier")
    command: str = Field(..., description="Slash command without leading slash")
    arguments: str | None = Field(None, description="Optional command arguments")
    cron: str = Field(..., description="Cron expression")
    enabled: bool = Field(..., description="Whether the job is enabled")
    overlap: Literal["skip", "queue"] = Field(..., description="Overlap handling mode")
    queue_max: int = Field(..., description="Maximum queued runs")
    queued_runs: int = Field(..., description="Queued runs waiting to execute")
    skipped_runs: int = Field(..., description="Skipped runs due to overlap limits")
    is_running: bool = Field(..., description="Whether the job is running")
    started_at: datetime | None = Field(None, description="Current run start time")
    elapsed_seconds: float | None = Field(None, description="Elapsed seconds for current run")
    last_finished_at: datetime | None = Field(None, description="Last run finish time")
    last_status: str | None = Field(None, description="Last run status")
    last_error: str | None = Field(None, description="Last run error message")
    last_cost_usd: float | None = Field(None, description="Last run cost in USD")
    last_duration_ms: int | None = Field(None, description="Last run duration in ms")
    next_run: datetime | None = Field(None, description="Next scheduled run time")
    timeout_seconds: int | None = Field(None, description="Per-run timeout override")
    max_budget_usd: float | None = Field(None, description="Per-run max budget override")
    model: str | None = Field(None, description="Optional model override")
    use_vault_lock: bool = Field(..., description="Whether vault lock is used")


class ScheduleStatusResponse(BaseModel):
    """Status response for schedule monitoring."""

    timezone: str = Field(..., description="Configured timezone")
    config_path: str = Field(..., description="Path to schedule config file")
    config_error: str | None = Field(None, description="Last config error")
    jobs: list[ScheduleJobStatus] = Field(default_factory=list)


class ScheduleCancelResponse(BaseModel):
    """Response for canceling a scheduled job."""

    status: Literal["cancelled", "not_running"] = Field(..., description="Cancel status")
