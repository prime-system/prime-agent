"""Schedule configuration loaded from .prime/schedule.yaml."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo

import yaml
from croniter import croniter
from pydantic import BaseModel, Field, field_validator, model_validator

if TYPE_CHECKING:
    from pathlib import Path


def get_system_timezone() -> str:
    """Return system timezone name, falling back to UTC if unavailable."""
    tzinfo = datetime.now().astimezone().tzinfo
    if tzinfo is None:
        return "UTC"

    tz_key = getattr(tzinfo, "key", None)
    if isinstance(tz_key, str) and tz_key:
        return tz_key

    tz_name = tzinfo.tzname(None)
    if tz_name:
        try:
            ZoneInfo(tz_name)
        except Exception:
            return "UTC"
        return tz_name

    return "UTC"


class ScheduleJobConfig(BaseModel):
    """Configuration for a scheduled slash command."""

    id: str = Field(..., description="Unique job identifier")
    command: str = Field(..., description="Slash command name without leading slash")
    arguments: str | None = Field(
        default=None, description="Optional arguments appended to the command"
    )
    cron: str = Field(..., description="Cron expression (5 fields)")
    overlap: Literal["skip", "queue"] = Field(
        default="skip", description="Overlap behavior when a job is already running"
    )
    queue_max: int = Field(
        default=1,
        description="Maximum queued runs when overlap=queue (new runs dropped if exceeded)",
        ge=0,
    )
    timeout_seconds: int | None = Field(
        default=None, description="Per-run timeout override in seconds"
    )
    max_budget_usd: float | None = Field(
        default=None, description="Per-run max budget override in USD"
    )
    model: str | None = Field(default=None, description="Optional model override")
    enabled: bool = Field(default=True, description="Enable or disable this job")
    use_vault_lock: bool = Field(
        default=False, description="Whether to acquire vault lock during execution"
    )

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not value or not isinstance(value, str):
            msg = "id must be a non-empty string"
            raise ValueError(msg)
        if any(char.isspace() for char in value):
            msg = "id must not contain whitespace"
            raise ValueError(msg)
        return value

    @field_validator("command")
    @classmethod
    def validate_command(cls, value: str) -> str:
        if not value or not isinstance(value, str):
            msg = "command must be a non-empty string"
            raise ValueError(msg)
        command = value.strip()
        if command.startswith("/"):
            msg = "command must not include leading '/'"
            raise ValueError(msg)
        if any(char.isspace() for char in command):
            msg = "command must not contain whitespace"
            raise ValueError(msg)
        return command

    @field_validator("cron")
    @classmethod
    def validate_cron(cls, value: str) -> str:
        if not value or not isinstance(value, str):
            msg = "cron must be a non-empty string"
            raise ValueError(msg)
        if not croniter.is_valid(value):
            msg = f"Invalid cron expression: {value}"
            raise ValueError(msg)
        return value

    @field_validator("timeout_seconds")
    @classmethod
    def validate_timeout(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if value <= 0:
            msg = "timeout_seconds must be a positive integer"
            raise ValueError(msg)
        return value

    @field_validator("max_budget_usd")
    @classmethod
    def validate_budget(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if value <= 0:
            msg = "max_budget_usd must be positive"
            raise ValueError(msg)
        return value


class ScheduleConfig(BaseModel):
    """Top-level schedule configuration."""

    timezone: str = Field(default_factory=get_system_timezone, description="IANA timezone name")
    jobs: list[ScheduleJobConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_job_ids(self) -> ScheduleConfig:
        job_ids = [job.id for job in self.jobs]
        duplicates = {job_id for job_id in job_ids if job_ids.count(job_id) > 1}
        if duplicates:
            msg = f"Duplicate job ids: {', '.join(sorted(duplicates))}"
            raise ValueError(msg)
        return self

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        if not value or not isinstance(value, str):
            msg = "timezone must be a non-empty string"
            raise ValueError(msg)
        try:
            ZoneInfo(value)
        except Exception as exc:
            msg = f"Invalid timezone: {value}"
            raise ValueError(msg) from exc
        return value


def load_schedule_config(vault_path: Path) -> ScheduleConfig:
    """
    Load schedule configuration from .prime/schedule.yaml.

    If the file doesn't exist, returns default configuration.
    """
    config_file = vault_path / ".prime" / "schedule.yaml"

    if not config_file.exists():
        return ScheduleConfig()

    with open(config_file, encoding="utf-8") as f:
        config_dict = yaml.safe_load(f)

    if config_dict is None:
        return ScheduleConfig()

    return ScheduleConfig(**config_dict)
