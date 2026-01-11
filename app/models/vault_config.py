"""Vault-specific configuration loaded from .prime/settings.yaml in the vault root."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

import yaml
from pydantic import BaseModel, Field, field_validator


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
            "{iso_year}, {iso_week} (ISO week number)"
        ),
    )

    @field_validator("folder")
    @classmethod
    def validate_folder(cls, v: str) -> str:
        """Validate folder path to prevent directory traversal."""
        if not v or not isinstance(v, str):
            msg = "folder must be a non-empty string"
            raise ValueError(msg)

        # Check for path traversal
        if ".." in v:
            msg = "folder cannot contain '..'"
            raise ValueError(msg)

        # Check for absolute paths
        if v.startswith(("/", "\\")):
            msg = "folder must be relative"
            raise ValueError(msg)

        # Check for null bytes
        if "\x00" in v:
            msg = "folder cannot contain null bytes"
            raise ValueError(msg)

        return v

    @field_validator("file_pattern")
    @classmethod
    def validate_file_pattern(cls, v: str) -> str:
        """Validate file pattern to prevent path traversal in filenames."""
        if not v or not isinstance(v, str):
            msg = "file_pattern must be a non-empty string"
            raise ValueError(msg)

        # Check for path traversal
        if ".." in v:
            msg = "file_pattern cannot contain '..'"
            raise ValueError(msg)

        # Check for path separators (these should be in placeholders, not literal paths)
        if "/" in v or "\\" in v:
            msg = "file_pattern cannot contain path separators"
            raise ValueError(msg)

        # Check for null bytes
        if "\x00" in v:
            msg = "file_pattern cannot contain null bytes"
            raise ValueError(msg)

        return v


class LogsConfig(BaseModel):
    """Configuration for the logs folder."""

    folder: str = Field(
        default=".prime/logs", description="Path to logs folder relative to vault root"
    )

    @field_validator("folder")
    @classmethod
    def validate_folder(cls, v: str) -> str:
        """Validate folder path to prevent directory traversal."""
        if not v or not isinstance(v, str):
            msg = "folder must be a non-empty string"
            raise ValueError(msg)

        # Check for path traversal
        if ".." in v:
            msg = "folder cannot contain '..'"
            raise ValueError(msg)

        # Check for absolute paths
        if v.startswith(("/", "\\")):
            msg = "folder must be relative"
            raise ValueError(msg)

        # Check for null bytes
        if "\x00" in v:
            msg = "folder cannot contain null bytes"
            raise ValueError(msg)

        return v


class VaultConfig(BaseModel):
    """
    Vault-specific configuration.

    Loaded from .prime/settings.yaml in the vault root. This allows users to customize
    how Prime interacts with their vault structure.
    """

    inbox: InboxConfig = Field(default_factory=InboxConfig)
    logs: LogsConfig = Field(default_factory=LogsConfig)


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
