"""
Tests for CommandService.

Tests cover:
- Listing commands from vault
- Finding command files by name
- Parsing command frontmatter and content
- Extracting argument placeholders
- Extracting bash commands
- Error handling for missing/invalid files
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.exceptions import VaultError
from app.models.command import CommandType
from app.services.command import CommandService


def test_list_commands_empty_vault(temp_vault: Path) -> None:
    """Test listing commands when no commands exist."""
    service = CommandService(str(temp_vault))

    response = service.list_commands()

    assert response.total == 0
    assert response.vault_commands == 0
    assert response.plugin_commands == 0
    assert response.mcp_commands == 0
    assert len(response.commands) == 0


def test_list_commands_single_command(temp_vault: Path) -> None:
    """Test listing a single command."""
    # Create .claude/commands directory
    commands_dir = temp_vault / ".claude" / "commands"
    commands_dir.mkdir(parents=True)

    # Create a simple command
    # Note: Multiple bracket pairs must be quoted in YAML to be valid
    command_file = commands_dir / "test-command.md"
    command_file.write_text(
        "---\n"
        "description: Test command\n"
        "argument-hint: '[arg1] [arg2]'\n"
        "---\n"
        "\n"
        "# Test Command\n"
        "\n"
        "This is a test command.\n"
    )

    service = CommandService(str(temp_vault))
    response = service.list_commands()

    assert response.total == 1
    assert response.vault_commands == 1
    assert len(response.commands) == 1

    cmd = response.commands[0]
    assert cmd.name == "test-command"
    assert cmd.description == "Test command"
    assert cmd.type == CommandType.VAULT
    assert cmd.argument_hint == "[arg1] [arg2]"
    assert cmd.namespace is None
    assert ".claude/commands/test-command.md" in cmd.path


def test_list_commands_with_namespace(temp_vault: Path) -> None:
    """Test listing commands in subdirectories with namespaces."""
    commands_dir = temp_vault / ".claude" / "commands"
    frontend_dir = commands_dir / "frontend"
    frontend_dir.mkdir(parents=True)

    # Create command in subdirectory
    command_file = frontend_dir / "component.md"
    command_file.write_text(
        """---
description: Create frontend component
---

Create a new React component.
"""
    )

    service = CommandService(str(temp_vault))
    response = service.list_commands()

    assert response.total == 1
    cmd = response.commands[0]
    assert cmd.name == "component"
    assert cmd.namespace == "frontend"
    assert cmd.description == "Create frontend component"


def test_list_commands_nested_namespaces(temp_vault: Path) -> None:
    """Test commands in deeply nested subdirectories."""
    commands_dir = temp_vault / ".claude" / "commands"
    nested_dir = commands_dir / "backend" / "api"
    nested_dir.mkdir(parents=True)

    command_file = nested_dir / "endpoint.md"
    command_file.write_text("# Create API endpoint\n\nCreate a new API endpoint.")

    service = CommandService(str(temp_vault))
    response = service.list_commands()

    assert response.total == 1
    cmd = response.commands[0]
    assert cmd.name == "endpoint"
    assert cmd.namespace == "backend:api"


def test_list_commands_multiple_files(temp_vault: Path) -> None:
    """Test listing multiple command files."""
    commands_dir = temp_vault / ".claude" / "commands"
    commands_dir.mkdir(parents=True)

    # Create multiple commands
    (commands_dir / "cmd1.md").write_text("# Command 1\nFirst command")
    (commands_dir / "cmd2.md").write_text("# Command 2\nSecond command")
    (commands_dir / "cmd3.md").write_text("# Command 3\nThird command")

    service = CommandService(str(temp_vault))
    response = service.list_commands()

    assert response.total == 3
    assert response.vault_commands == 3
    names = {cmd.name for cmd in response.commands}
    assert names == {"cmd1", "cmd2", "cmd3"}


def test_list_commands_ignores_non_md_files(temp_vault: Path) -> None:
    """Test that non-markdown files are ignored."""
    commands_dir = temp_vault / ".claude" / "commands"
    commands_dir.mkdir(parents=True)

    # Create md and non-md files
    (commands_dir / "valid.md").write_text("# Valid command")
    (commands_dir / "readme.txt").write_text("Not a command")
    (commands_dir / "config.yaml").write_text("also: not-a-command")

    service = CommandService(str(temp_vault))
    response = service.list_commands()

    assert response.total == 1
    assert response.commands[0].name == "valid"


def test_get_command_detail_basic(temp_vault: Path) -> None:
    """Test getting detailed command information."""
    commands_dir = temp_vault / ".claude" / "commands"
    commands_dir.mkdir(parents=True)

    command_file = commands_dir / "review.md"
    command_file.write_text(
        "---\n"
        "description: Review code\n"
        "allowed-tools:\n"
        "  - Read\n"
        "  - Grep\n"
        "argument-hint: [file-path]\n"
        "model: claude-3-5-haiku-20241022\n"
        "---\n"
        "\n"
        "# Code Review\n"
        "\n"
        "Review the code in $1 for:\n"
        "- Security issues\n"
        "- Performance problems\n"
        "- Code style\n"
    )

    service = CommandService(str(temp_vault))
    detail = service.get_command_detail("review")

    assert detail is not None
    assert detail.info.name == "review"
    assert detail.info.description == "Review code"
    assert detail.frontmatter is not None
    assert detail.frontmatter.description == "Review code"
    assert detail.frontmatter.allowed_tools == ["Read", "Grep"]
    assert detail.frontmatter.argument_hint == "[file-path]"
    assert detail.frontmatter.model == "claude-3-5-haiku-20241022"
    assert "Code Review" in detail.content
    assert "Review the code" in detail.content


def test_get_command_detail_with_arguments(temp_vault: Path) -> None:
    """Test extracting argument placeholders."""
    commands_dir = temp_vault / ".claude" / "commands"
    commands_dir.mkdir(parents=True)

    command_file = commands_dir / "deploy.md"
    command_file.write_text(
        """Deploy to $1 environment with config $2.

Use all remaining args: $ARGUMENTS
"""
    )

    service = CommandService(str(temp_vault))
    detail = service.get_command_detail("deploy")

    assert detail is not None
    assert detail.has_arguments is True
    assert "$1" in detail.argument_placeholders
    assert "$2" in detail.argument_placeholders
    assert "$ARGUMENTS" in detail.argument_placeholders
    assert len(detail.argument_placeholders) == 3


def test_get_command_detail_with_bash_commands(temp_vault: Path) -> None:
    """Test extracting bash commands."""
    commands_dir = temp_vault / ".claude" / "commands"
    commands_dir.mkdir(parents=True)

    command_file = commands_dir / "commit.md"
    command_file.write_text(
        """---
allowed-tools: Bash(git:*)
---

# Git Commit

Current status: !`git status`
Recent commits: !`git log --oneline -5`
"""
    )

    service = CommandService(str(temp_vault))
    detail = service.get_command_detail("commit")

    assert detail is not None
    assert detail.has_bash_execution is True
    assert "git status" in detail.bash_commands
    assert "git log --oneline -5" in detail.bash_commands
    assert len(detail.bash_commands) == 2


def test_get_command_detail_with_file_references(temp_vault: Path) -> None:
    """Test detecting file references."""
    commands_dir = temp_vault / ".claude" / "commands"
    commands_dir.mkdir(parents=True)

    command_file = commands_dir / "analyze.md"
    command_file.write_text(
        """Analyze the code in @src/main.py and compare with @tests/test_main.py
"""
    )

    service = CommandService(str(temp_vault))
    detail = service.get_command_detail("analyze")

    assert detail is not None
    assert detail.has_file_references is True


def test_get_command_detail_not_found(temp_vault: Path) -> None:
    """Test getting command that doesn't exist."""
    service = CommandService(str(temp_vault))
    detail = service.get_command_detail("nonexistent")

    assert detail is None


def test_get_command_detail_in_subdirectory(temp_vault: Path) -> None:
    """Test getting command from subdirectory."""
    commands_dir = temp_vault / ".claude" / "commands"
    backend_dir = commands_dir / "backend"
    backend_dir.mkdir(parents=True)

    command_file = backend_dir / "test.md"
    command_file.write_text("# Backend test\nRun backend tests")

    service = CommandService(str(temp_vault))
    detail = service.get_command_detail("test")

    assert detail is not None
    assert detail.info.name == "test"
    assert detail.info.namespace == "backend"


def test_list_commands_vault_not_exists() -> None:
    """Test listing commands when vault doesn't exist."""
    service = CommandService("/nonexistent/vault/path")

    with pytest.raises(VaultError) as exc_info:
        service.list_commands()

    assert "Vault path does not exist" in str(exc_info.value)


def test_get_command_detail_vault_not_exists() -> None:
    """Test getting command detail when vault doesn't exist."""
    service = CommandService("/nonexistent/vault/path")

    with pytest.raises(VaultError) as exc_info:
        service.get_command_detail("any-command")

    assert "Vault path does not exist" in str(exc_info.value)


def test_parse_command_with_no_frontmatter(temp_vault: Path) -> None:
    """Test parsing command without frontmatter."""
    commands_dir = temp_vault / ".claude" / "commands"
    commands_dir.mkdir(parents=True)

    command_file = commands_dir / "simple.md"
    command_file.write_text(
        """# Simple Command

This command has no frontmatter.
Just plain markdown content.
"""
    )

    service = CommandService(str(temp_vault))
    response = service.list_commands()

    assert response.total == 1
    cmd = response.commands[0]
    assert cmd.name == "simple"
    assert cmd.description == "Simple Command"  # Extracted from first line
    assert cmd.argument_hint is None

    # Get detail
    detail = service.get_command_detail("simple")
    assert detail is not None
    assert detail.frontmatter is not None
    assert detail.frontmatter.description is None  # No frontmatter description
    assert "This command has no frontmatter" in detail.content


def test_parse_command_with_empty_frontmatter(temp_vault: Path) -> None:
    """Test parsing command with empty frontmatter."""
    commands_dir = temp_vault / ".claude" / "commands"
    commands_dir.mkdir(parents=True)

    command_file = commands_dir / "empty.md"
    command_file.write_text(
        """---
---

# Empty Frontmatter

Command with empty frontmatter block.
"""
    )

    service = CommandService(str(temp_vault))
    response = service.list_commands()

    assert response.total == 1
    cmd = response.commands[0]
    assert cmd.name == "empty"


def test_extract_first_line_description(temp_vault: Path) -> None:
    """Test extracting description from first line when no frontmatter."""
    commands_dir = temp_vault / ".claude" / "commands"
    commands_dir.mkdir(parents=True)

    command_file = commands_dir / "cmd.md"
    command_file.write_text(
        """## This is the First Line

Additional content here.
"""
    )

    service = CommandService(str(temp_vault))
    response = service.list_commands()

    cmd = response.commands[0]
    assert cmd.description == "This is the First Line"  # Markdown # stripped


def test_command_with_disable_model_invocation(temp_vault: Path) -> None:
    """Test command with disable-model-invocation flag."""
    commands_dir = temp_vault / ".claude" / "commands"
    commands_dir.mkdir(parents=True)

    command_file = commands_dir / "internal.md"
    command_file.write_text(
        """---
description: Internal command
disable-model-invocation: true
---

This command should not be invoked by SlashCommand tool.
"""
    )

    service = CommandService(str(temp_vault))
    detail = service.get_command_detail("internal")

    assert detail is not None
    assert detail.frontmatter is not None
    assert detail.frontmatter.disable_model_invocation is True
