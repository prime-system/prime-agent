"""Vault-specific configuration loaded from .prime/settings.yaml in the vault root."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class InboxConfig(BaseModel):
    """Configuration for the inbox folder and capture storage."""

    folder: str = Field(default=".prime/inbox", description="Path to inbox folder relative to vault root")
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
            "{title} (AI-generated title using Claude Haiku)"
        ),
    )


class LogsConfig(BaseModel):
    """Configuration for the logs folder."""

    folder: str = Field(default=".prime/logs", description="Path to logs folder relative to vault root")


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
