"""
Validated data models for capture file frontmatter.

Provides Pydantic models for strict validation of capture metadata.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


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
    Validated frontmatter for Claude command files.

    Allows vault-specific customization of agent behavior.

    Schema:
        ---
        description: Process and organize brain dumps
        version: 1
        requires_lock: true
        ---
    """

    description: str = Field(
        default="", description="Command description"
    )
    version: int = Field(default=1, description="Command version")
    requires_lock: bool = Field(
        default=False,
        description="Whether command requires vault lock",
    )
