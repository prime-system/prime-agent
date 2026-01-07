"""
Validated data models for capture file frontmatter.

Provides Pydantic models for strict validation of capture metadata.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class CaptureSource(str, Enum):
    """Valid capture source devices."""

    IPHONE = "iphone"
    IPAD = "ipad"
    MAC = "mac"


class CaptureInput(str, Enum):
    """Valid capture input methods."""

    VOICE = "voice"
    TEXT = "text"


class CaptureFrontmatter(BaseModel):
    """
    Validated frontmatter for capture files.

    Schema:
        ---
        id: 2026-01-02T14:30:00Z-iphone
        captured_at: 2026-01-02T14:30:00Z
        source: iphone
        input: voice
        processed: false
        context:
          app: shortcuts
        ---
    """

    id: str = Field(..., description="Unique capture ID")
    captured_at: str = Field(
        ..., description="ISO8601 timestamp when captured"
    )
    source: str = Field(
        ..., description="Source device (iphone, ipad, mac)"
    )
    input: str = Field(..., description="Input method (voice, text)")
    processed: bool = Field(
        default=False, description="Whether capture has been processed"
    )
    context: dict[str, object] = Field(
        default_factory=dict, description="Additional context metadata"
    )

    def model_post_init(self, __context: object) -> None:
        """Validate enum values after model construction."""
        if self.source not in [e.value for e in CaptureSource]:
            raise ValueError(
                f"Invalid source '{self.source}': "
                f"must be one of {[e.value for e in CaptureSource]}"
            )

        if self.input not in [e.value for e in CaptureInput]:
            raise ValueError(
                f"Invalid input '{self.input}': "
                f"must be one of {[e.value for e in CaptureInput]}"
            )


class CommandFrontmatter(BaseModel):
    """
    Validated frontmatter for Claude slash command files.

    Follows the Claude Code slash command specification:
    https://code.claude.com/docs/en/slash-commands.md

    Schema:
        ---
        allowed-tools: Bash(git:*), Read, Write
        argument-hint: [pr-number] [priority]
        description: Review pull request
        model: claude-3-5-haiku-20241022
        disable-model-invocation: false
        ---
    """

    allowed_tools: list[str] | None = Field(
        default=None,
        description="List of tools the command can use",
        alias="allowed-tools",
    )
    argument_hint: str | None = Field(
        default=None,
        description="Arguments expected for the slash command",
        alias="argument-hint",
    )
    description: str | None = Field(
        default=None, description="Brief description of the command"
    )
    model: str | None = Field(
        default=None, description="Specific model string"
    )
    disable_model_invocation: bool = Field(
        default=False,
        description="Whether to prevent SlashCommand tool from calling this command",
        alias="disable-model-invocation",
    )

    model_config = {
        "populate_by_name": True  # Allow both snake_case and kebab-case field names
    }

    @field_validator("argument_hint", mode="before")
    @classmethod
    def normalize_argument_hint(cls, value: Any) -> str | None:
        """
        Normalize argument-hint from YAML format to string.

        In YAML, unquoted brackets are parsed as arrays:
        - `argument-hint: [message]` → YAML parses as `['message']` (list)
        - `argument-hint: '[message]'` → YAML parses as `'[message]'` (string)

        This validator handles both formats to match Claude Code's behavior.
        """
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            # Convert list to bracketed string format
            # ['message'] → '[message]'
            # ['pr-number', 'priority'] → '[pr-number] [priority]'
            return " ".join(f"[{item}]" for item in value)
        return str(value)
