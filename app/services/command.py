"""Service for managing Claude slash commands."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from app.exceptions import VaultError
from app.models.command import (
    CommandDetail,
    CommandInfo,
    CommandListResponse,
    CommandType,
)
from app.utils.frontmatter import parse_and_validate_command

logger = logging.getLogger(__name__)


class CommandService:
    """Service for scanning and parsing Claude slash commands."""

    def __init__(self, vault_path: str):
        """
        Initialize CommandService.

        Args:
            vault_path: Path to the vault root directory
        """
        self.vault_path = Path(vault_path)
        self.commands_dir = self.vault_path / ".claude" / "commands"

    def list_commands(self) -> CommandListResponse:
        """
        List all available slash commands.

        Returns:
            CommandListResponse with all discovered commands

        Raises:
            VaultError: If vault is inaccessible
        """
        if not self.vault_path.exists():
            msg = "Vault path does not exist"
            raise VaultError(
                msg,
                context={"vault_path": str(self.vault_path)},
            )

        commands: list[CommandInfo] = []

        # Scan vault commands
        if self.commands_dir.exists():
            vault_commands = self._scan_directory(self.commands_dir, CommandType.VAULT)
            commands.extend(vault_commands)
            logger.info(
                "Scanned vault commands",
                extra={
                    "count": len(vault_commands),
                    "commands_dir": str(self.commands_dir),
                },
            )

        # Count by type
        vault_count = sum(1 for c in commands if c.type == CommandType.VAULT)
        plugin_count = sum(1 for c in commands if c.type == CommandType.PLUGIN)
        mcp_count = sum(1 for c in commands if c.type == CommandType.MCP)

        return CommandListResponse(
            commands=commands,
            total=len(commands),
            vault_commands=vault_count,
            plugin_commands=plugin_count,
            mcp_commands=mcp_count,
        )

    def get_command_detail(self, command_name: str) -> CommandDetail | None:
        """
        Get detailed information about a specific command.

        Args:
            command_name: Name of the command (without leading slash)

        Returns:
            CommandDetail if found, None otherwise

        Raises:
            VaultError: If vault is inaccessible or command file cannot be read
        """
        if not self.vault_path.exists():
            msg = "Vault path does not exist"
            raise VaultError(
                msg,
                context={"vault_path": str(self.vault_path)},
            )

        # Search for command in vault
        if self.commands_dir.exists():
            command_file = self._find_command_file(command_name)
            if command_file:
                return self._parse_command_detail(command_file, CommandType.VAULT)

        logger.warning(
            "Command not found",
            extra={"command_name": command_name, "vault_path": str(self.vault_path)},
        )
        return None

    def _scan_directory(
        self, directory: Path, command_type: CommandType, namespace: str | None = None
    ) -> list[CommandInfo]:
        """
        Recursively scan a directory for command files.

        Args:
            directory: Directory to scan
            command_type: Type of commands in this directory
            namespace: Current namespace from parent directory

        Returns:
            List of CommandInfo objects
        """
        commands: list[CommandInfo] = []

        try:
            for item in directory.iterdir():
                if item.is_dir():
                    # Recursively scan subdirectories with namespace
                    subdir_namespace = f"{namespace}:{item.name}" if namespace else item.name
                    subcommands = self._scan_directory(item, command_type, subdir_namespace)
                    commands.extend(subcommands)
                elif item.suffix == ".md":
                    # Parse command file
                    try:
                        command_info = self._parse_command_info(item, command_type, namespace)
                        commands.append(command_info)
                    except Exception as e:
                        logger.warning(
                            "Failed to parse command file",
                            extra={
                                "file": str(item),
                                "error": str(e),
                                "error_type": type(e).__name__,
                            },
                        )
                        # Continue scanning other files
        except PermissionError as e:
            logger.error(
                "Permission denied scanning directory",
                extra={
                    "directory": str(directory),
                    "error": str(e),
                },
            )
            msg = "Permission denied accessing commands directory"
            raise VaultError(
                msg,
                context={"directory": str(directory)},
            ) from e

        return commands

    def _parse_command_info(
        self, file_path: Path, command_type: CommandType, namespace: str | None
    ) -> CommandInfo:
        """
        Parse basic command information from a file.

        Args:
            file_path: Path to command file
            command_type: Type of command
            namespace: Namespace from directory structure

        Returns:
            CommandInfo object

        Raises:
            VaultError: If file cannot be read or parsed
        """
        try:
            content = file_path.read_text(encoding="utf-8")
            frontmatter, body = parse_and_validate_command(content)

            # Extract command name from filename
            command_name = file_path.stem

            # Get description from frontmatter or first line of body
            description = frontmatter.description or self._extract_first_line(body)

            # Get relative path from vault root
            relative_path = str(file_path.relative_to(self.vault_path))

            return CommandInfo(
                name=command_name,
                description=description,
                type=command_type,
                namespace=namespace,
                argument_hint=frontmatter.argument_hint,
                path=relative_path,
                file_name=file_path.name,
            )
        except OSError as e:
            logger.error(
                "Failed to read command file",
                extra={
                    "file": str(file_path),
                    "error": str(e),
                },
            )
            msg = "Failed to read command file"
            raise VaultError(
                msg,
                context={"file": str(file_path)},
            ) from e

    def _parse_command_detail(self, file_path: Path, command_type: CommandType) -> CommandDetail:
        """
        Parse detailed command information including analysis of content.

        Args:
            file_path: Path to command file
            command_type: Type of command

        Returns:
            CommandDetail object

        Raises:
            VaultError: If file cannot be read or parsed
        """
        try:
            raw_content = file_path.read_text(encoding="utf-8")
            frontmatter, body = parse_and_validate_command(raw_content)

            # Determine namespace from file path
            commands_dir = self.vault_path / ".claude" / "commands"
            relative_to_commands = file_path.relative_to(commands_dir)
            namespace = (
                str(relative_to_commands.parent) if relative_to_commands.parent != Path() else None
            )

            # Parse command info
            command_info = self._parse_command_info(file_path, command_type, namespace)

            # Analyze content for features
            arg_placeholders = self._extract_argument_placeholders(body)
            bash_commands = self._extract_bash_commands(body)

            return CommandDetail(
                info=command_info,
                frontmatter=frontmatter,
                content=body,
                raw_content=raw_content,
                has_arguments=len(arg_placeholders) > 0,
                argument_placeholders=arg_placeholders,
                has_bash_execution=len(bash_commands) > 0,
                bash_commands=bash_commands,
                has_file_references="@" in body,
            )
        except OSError as e:
            logger.error(
                "Failed to read command file",
                extra={
                    "file": str(file_path),
                    "error": str(e),
                },
            )
            msg = "Failed to read command file"
            raise VaultError(
                msg,
                context={"file": str(file_path)},
            ) from e

    def _find_command_file(self, command_name: str) -> Path | None:
        """
        Find command file by name, searching all subdirectories.

        Args:
            command_name: Name of command (without .md extension)

        Returns:
            Path to command file if found, None otherwise
        """
        if not self.commands_dir.exists():
            return None

        # Search for exact match: command_name.md
        for md_file in self.commands_dir.rglob(f"{command_name}.md"):
            return md_file

        return None

    def _extract_first_line(self, text: str) -> str:
        """
        Extract first non-empty line from text for description.

        Args:
            text: Markdown content

        Returns:
            First line stripped of markdown formatting
        """
        lines = text.strip().split("\n")
        for line in lines:
            clean_line = line.strip().lstrip("#").strip()
            if clean_line:
                # Limit to 100 characters
                return clean_line[:100]
        return ""

    def _extract_argument_placeholders(self, content: str) -> list[str]:
        """
        Extract argument placeholders from command content.

        Finds: $ARGUMENTS, $1, $2, etc.

        Args:
            content: Command markdown content

        Returns:
            List of unique placeholders found
        """
        placeholders = set()

        # Find $ARGUMENTS
        if "$ARGUMENTS" in content:
            placeholders.add("$ARGUMENTS")

        # Find positional arguments ($1, $2, etc.)
        positional_pattern = r"\$(\d+)"
        matches = re.findall(positional_pattern, content)
        for match in matches:
            placeholders.add(f"${match}")

        return sorted(placeholders)

    def _extract_bash_commands(self, content: str) -> list[str]:
        """
        Extract bash commands from command content.

        Finds commands with !`...` syntax.

        Args:
            content: Command markdown content

        Returns:
            List of bash commands found
        """
        bash_commands = []

        # Find bash execution patterns: !`command`
        bash_pattern = r"!`([^`]+)`"
        matches = re.findall(bash_pattern, content)
        bash_commands.extend(matches)

        return bash_commands
