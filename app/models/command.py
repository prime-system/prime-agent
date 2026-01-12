"""Models for Claude slash commands."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.models.frontmatter import CommandFrontmatter  # noqa: TC001


class CommandType(str, Enum):
    """Type of slash command."""

    VAULT = "vault"  # Commands from vault's .claude/commands/
    PLUGIN = "plugin"  # Commands from installed plugins
    MCP = "mcp"  # Commands from MCP servers


class CommandInfo(BaseModel):
    """Information about a slash command."""

    name: str = Field(..., description="Command name (without leading slash)")
    description: str = Field(..., description="Brief description of the command")
    type: CommandType = Field(..., description="Type of command (vault/plugin/mcp)")
    namespace: str | None = Field(
        None,
        description="Namespace from subdirectory (e.g., 'frontend' for commands/frontend/test.md)",
    )
    argument_hint: str | None = Field(None, description="Expected arguments for the command")
    path: str = Field(..., description="Relative path to the command file")
    file_name: str = Field(..., description="Name of the command file")


class CommandDetail(BaseModel):
    """Detailed information about a slash command."""

    info: CommandInfo = Field(..., description="Basic command information")
    frontmatter: CommandFrontmatter | None = Field(None, description="Parsed frontmatter metadata")
    content: str = Field(..., description="Full markdown content (without frontmatter)")
    raw_content: str = Field(..., description="Raw file content including frontmatter")
    has_arguments: bool = Field(False, description="Whether command uses argument placeholders")
    argument_placeholders: list[str] = Field(
        default_factory=list,
        description="List of argument placeholders found ($ARGUMENTS, $1, $2, etc.)",
    )
    has_bash_execution: bool = Field(False, description="Whether command executes bash commands")
    bash_commands: list[str] = Field(
        default_factory=list, description="List of bash commands found (with ! prefix)"
    )
    has_file_references: bool = Field(False, description="Whether command references files")


class CommandListResponse(BaseModel):
    """Response for listing all commands."""

    commands: list[CommandInfo] = Field(
        default_factory=list, description="List of available commands"
    )
    total: int = Field(..., description="Total number of commands")
    vault_commands: int = Field(0, description="Number of vault commands")
    plugin_commands: int = Field(0, description="Number of plugin commands")
    mcp_commands: int = Field(0, description="Number of MCP commands")


class TriggerCommandRequest(BaseModel):
    """Request to trigger a command manually."""

    arguments: str | None = Field(None, description="Optional arguments string for the command")


class TriggerCommandResponse(BaseModel):
    """Response after triggering a command."""

    run_id: str = Field(..., description="Unique run identifier")
    status: str = Field(..., description="Initial status (started)")
    poll_url: str = Field(..., description="URL to poll for run status and output")


class CommandRunEvent(BaseModel):
    """Single event from a command run."""

    event_id: int = Field(..., description="Unique event ID for polling cursor")
    type: str = Field(..., description="Event type (text, tool_use, thinking, complete, error)")
    # Additional fields vary by type - flattened into this model


class CommandRunStatusResponse(BaseModel):
    """Response for command run status and events."""

    run_id: str = Field(..., description="Run identifier")
    command_name: str = Field(..., description="Command that was executed")
    status: str = Field(..., description="Run status (started, running, completed, error)")
    started_at: str = Field(..., description="ISO timestamp when run started")
    completed_at: str | None = Field(None, description="ISO timestamp when run completed")
    cost_usd: float | None = Field(None, description="Total API cost in USD")
    duration_ms: int | None = Field(None, description="Total duration in milliseconds")
    error: str | None = Field(None, description="Error message if status is error")
    events: list[dict[str, Any]] = Field(
        default_factory=list, description="List of events since cursor"
    )
    next_cursor: int = Field(
        ...,
        description="Next event ID to use for polling (use as `after`; -1 if no events yet)",
    )
    dropped_before: int = Field(
        0, description="First event ID that was dropped from buffer (0 if none)"
    )
