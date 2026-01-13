"""Vault-specific configuration loaded from .prime/settings.yaml in the vault root."""

from __future__ import annotations

import re
from pathlib import Path  # noqa: TC003
from string import Formatter

import yaml
from pydantic import BaseModel, Field, field_validator

_ABSOLUTE_PATH_PATTERN = re.compile(r"^[a-zA-Z]:[\\/]")
_ALLOWED_TEMPLATE_PLACEHOLDERS = {
    "year",
    "month",
    "day",
    "hour",
    "minute",
    "second",
    "source",
    "iso_year",
    "iso_week",
    "week",
}


def _validate_relative_folder(folder: str) -> str:
    """Validate folder path to prevent directory traversal.

    Leading path separators are treated as vault-rooted and stripped.
    """
    if not folder or not isinstance(folder, str):
        msg = "folder must be a non-empty string"
        raise ValueError(msg)

    normalized = folder.lstrip("/\\")
    if not normalized:
        msg = "folder must be a non-empty string"
        raise ValueError(msg)

    # Check for path traversal
    if ".." in normalized:
        msg = "folder cannot contain '..'"
        raise ValueError(msg)

    # Check for null bytes
    if "\x00" in normalized:
        msg = "folder cannot contain null bytes"
        raise ValueError(msg)

    return normalized


def _validate_template_placeholders(template: str, field_name: str) -> None:
    formatter = Formatter()
    try:
        parsed = list(formatter.parse(template))
    except ValueError as exc:
        msg = f"{field_name} has invalid placeholder syntax"
        raise ValueError(msg) from exc

    invalid_placeholders: set[str] = set()
    for _, field, format_spec, conversion in parsed:
        if field is None:
            continue
        if field == "":
            msg = f"{field_name} cannot contain empty placeholders"
            raise ValueError(msg)
        if format_spec:
            msg = f"{field_name} placeholders cannot include format specs"
            raise ValueError(msg)
        if conversion:
            msg = f"{field_name} placeholders cannot include conversions"
            raise ValueError(msg)
        if field not in _ALLOWED_TEMPLATE_PLACEHOLDERS:
            invalid_placeholders.add(field)

    if invalid_placeholders:
        invalid_list = ", ".join(sorted(invalid_placeholders))
        msg = f"{field_name} contains unsupported placeholders: {invalid_list}"
        raise ValueError(msg)


def _validate_template_string(
    template: str,
    field_name: str,
    allow_path_separators: bool,
) -> str:
    if not template or not isinstance(template, str):
        msg = f"{field_name} must be a non-empty string"
        raise ValueError(msg)

    if "\x00" in template:
        msg = f"{field_name} cannot contain null bytes"
        raise ValueError(msg)

    if ".." in template:
        msg = f"{field_name} cannot contain '..'"
        raise ValueError(msg)

    if allow_path_separators:
        if template.startswith(("/", "\\")) or _ABSOLUTE_PATH_PATTERN.match(template):
            msg = f"{field_name} cannot be an absolute path"
            raise ValueError(msg)
    elif "/" in template or "\\" in template:
        msg = f"{field_name} cannot contain path separators"
        raise ValueError(msg)

    _validate_template_placeholders(template, field_name)

    return template


class InboxConfig(BaseModel):
    """Configuration for the inbox folder and capture storage."""

    folder: str = Field(
        default=".prime/inbox", description="Path to inbox folder relative to vault root"
    )
    weekly_subfolders: bool = Field(
        default=True, description="Create weekly subfolders (e.g., 2026-W01/)"
    )
    file_pattern: str = Field(
        default="{year}-{month}-{day}_{hour}-{minute}-{second}_{source}.md",
        description=(
            "Filename pattern for capture files. "
            "Available placeholders: "
            "{year}, {month}, {day}, {hour}, {minute}, {second}, "
            "{source} (iphone/ipad/mac), "
            "{iso_year}, {iso_week} (ISO week number), "
            "{week} (alias for {iso_week})"
        ),
    )

    @field_validator("folder")
    @classmethod
    def validate_folder(cls, v: str) -> str:
        """Validate folder path to prevent directory traversal."""
        return _validate_relative_folder(v)

    @field_validator("file_pattern")
    @classmethod
    def validate_file_pattern(cls, v: str) -> str:
        """Validate file pattern to prevent path traversal in filenames."""
        return _validate_template_string(v, "file_pattern", allow_path_separators=False)


class LogsConfig(BaseModel):
    """Configuration for the logs folder."""

    folder: str = Field(
        default=".prime/logs", description="Path to logs folder relative to vault root"
    )

    @field_validator("folder")
    @classmethod
    def validate_folder(cls, v: str) -> str:
        """Validate folder path to prevent directory traversal."""
        return _validate_relative_folder(v)


class DailyConfig(BaseModel):
    """Configuration for the Daily folder and today's note."""

    folder: str = Field(default="Daily", description="Path to Daily folder relative to vault root")
    today_note: str = Field(
        default="{year}-{month}-{day}.md",
        description="Filename or relative path template for today's note",
    )

    @field_validator("folder")
    @classmethod
    def validate_folder(cls, v: str) -> str:
        """Validate folder path to prevent directory traversal."""
        return _validate_relative_folder(v)

    @field_validator("today_note")
    @classmethod
    def validate_today_note(cls, v: str) -> str:
        """Validate today note template to prevent path traversal."""
        return _validate_template_string(v, "today_note", allow_path_separators=True)


class VaultConfig(BaseModel):
    """
    Vault-specific configuration.

    Loaded from .prime/settings.yaml in the vault root. This allows users to customize
    how Prime interacts with their vault structure.
    """

    inbox: InboxConfig = Field(default_factory=InboxConfig)
    logs: LogsConfig = Field(default_factory=LogsConfig)
    daily: DailyConfig | None = Field(default=None)


def load_vault_config(vault_path: Path) -> VaultConfig:
    """
    Load vault configuration from .prime/settings.yaml.

    If the file doesn't exist, returns default configuration.
    """
    config_file = vault_path / ".prime" / "settings.yaml"

    if not config_file.exists():
        return VaultConfig()

    with open(config_file, encoding="utf-8") as f:
        config_dict = yaml.safe_load(f)

    if config_dict is None:
        return VaultConfig()

    return VaultConfig(**config_dict)
