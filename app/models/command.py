"""Models for Claude slash commands."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.models.frontmatter import CommandFrontmatter


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
    argument_hint: str | None = Field(
        None, description="Expected arguments for the command"
    )
    path: str = Field(..., description="Relative path to the command file")
    file_name: str = Field(..., description="Name of the command file")


class CommandDetail(BaseModel):
    """Detailed information about a slash command."""

    info: CommandInfo = Field(..., description="Basic command information")
    frontmatter: CommandFrontmatter | None = Field(
        None, description="Parsed frontmatter metadata"
    )
    content: str = Field(..., description="Full markdown content (without frontmatter)")
    raw_content: str = Field(..., description="Raw file content including frontmatter")
    has_arguments: bool = Field(
        False, description="Whether command uses argument placeholders"
    )
    argument_placeholders: list[str] = Field(
        default_factory=list,
        description="List of argument placeholders found ($ARGUMENTS, $1, $2, etc.)",
    )
    has_bash_execution: bool = Field(
        False, description="Whether command executes bash commands"
    )
    bash_commands: list[str] = Field(
        default_factory=list, description="List of bash commands found (with ! prefix)"
    )
    has_file_references: bool = Field(
        False, description="Whether command references files"
    )


class CommandListResponse(BaseModel):
    """Response for listing all commands."""

    commands: list[CommandInfo] = Field(
        default_factory=list, description="List of available commands"
    )
    total: int = Field(..., description="Total number of commands")
    vault_commands: int = Field(0, description="Number of vault commands")
    plugin_commands: int = Field(0, description="Number of plugin commands")
    mcp_commands: int = Field(0, description="Number of MCP commands")
