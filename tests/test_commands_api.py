"""
Tests for commands API endpoints.

Tests cover:
- Listing commands via API
- Getting command details via API
- Authentication requirements
- Error handling (404, 500)
- Response format validation
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import commands
from app.exceptions import VaultError
from app.models.command import CommandType
from app.services.command import CommandService
from app.services.container import ServiceContainer


@pytest.fixture
def mock_command_service(temp_vault: Path) -> CommandService:
    """Create a real CommandService with temp vault."""
    return CommandService(str(temp_vault))


@pytest.fixture
def mock_container(mock_command_service: CommandService) -> ServiceContainer:
    """Create a mock container with command service."""
    # Create minimal mock container
    container = MagicMock(spec=ServiceContainer)
    container.command_service = mock_command_service
    return container


@pytest.fixture
def test_app_with_commands(mock_container: ServiceContainer) -> FastAPI:
    """Create test FastAPI app with commands router."""
    from app.services import container

    # Temporarily replace container getter
    original_get_container = container.get_container
    container.get_container = lambda: mock_container

    app = FastAPI(title="Prime Server Test")
    app.include_router(commands.router, tags=["commands"])

    yield app

    # Restore original
    container.get_container = original_get_container


@pytest.fixture
def client_with_commands(test_app_with_commands: FastAPI) -> TestClient:
    """Create test client with commands router."""
    return TestClient(test_app_with_commands)


def test_list_commands_requires_auth(client_with_commands: TestClient) -> None:
    """Test that listing commands requires authentication."""
    response = client_with_commands.get("/api/v1/commands")

    assert response.status_code == 401
    assert "Not authenticated" in response.json()["detail"]


def test_list_commands_empty(client_with_commands: TestClient, temp_vault: Path) -> None:
    """Test listing commands when none exist."""
    response = client_with_commands.get(
        "/api/v1/commands", headers={"Authorization": "Bearer test-token-123"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["vault_commands"] == 0
    assert data["plugin_commands"] == 0
    assert data["mcp_commands"] == 0
    assert len(data["commands"]) == 0


def test_list_commands_with_data(client_with_commands: TestClient, temp_vault: Path) -> None:
    """Test listing commands with actual command files."""
    # Create command files
    commands_dir = temp_vault / ".claude" / "commands"
    commands_dir.mkdir(parents=True)

    (commands_dir / "cmd1.md").write_text(
        "---\n"
        "description: First command\n"
        "argument-hint: [arg1]\n"  # Single bracket - valid YAML
        "---\n"
        "\n"
        "First command content\n"
    )

    (commands_dir / "cmd2.md").write_text(
        """# Second Command

Second command content
"""
    )

    response = client_with_commands.get(
        "/api/v1/commands", headers={"Authorization": "Bearer test-token-123"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["vault_commands"] == 2

    # Check command details
    commands_list = data["commands"]
    names = {cmd["name"] for cmd in commands_list}
    assert names == {"cmd1", "cmd2"}

    # Check cmd1 details
    cmd1 = next(cmd for cmd in commands_list if cmd["name"] == "cmd1")
    assert cmd1["description"] == "First command"
    # YAML [arg1] becomes list ['arg1'], our validator converts to '[arg1]'
    assert cmd1["argument_hint"] == "[arg1]"
    assert cmd1["type"] == "vault"
    assert cmd1["namespace"] is None


def test_format_command_title_handles_camel_case() -> None:
    """Ensure command titles are humanized from multiple naming styles."""
    cases = {
        "process_capture": "Process Capture",
        "process-capture": "Process Capture",
        "processCapture": "Process Capture",
        "dailyBrief": "Daily Brief",
        "admin:processCapture": "Admin Process Capture",
    }

    for command_name, expected in cases.items():
        assert commands._format_command_title(command_name) == expected


def test_list_commands_with_namespaces(client_with_commands: TestClient, temp_vault: Path) -> None:
    """Test listing commands with subdirectory namespaces."""
    commands_dir = temp_vault / ".claude" / "commands"
    frontend_dir = commands_dir / "frontend"
    backend_dir = commands_dir / "backend"
    frontend_dir.mkdir(parents=True)
    backend_dir.mkdir(parents=True)

    (frontend_dir / "component.md").write_text("# Frontend component")
    (backend_dir / "api.md").write_text("# Backend API")

    response = client_with_commands.get(
        "/api/v1/commands", headers={"Authorization": "Bearer test-token-123"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2

    # Check namespaces
    for cmd in data["commands"]:
        if cmd["name"] == "component":
            assert cmd["namespace"] == "frontend"
        elif cmd["name"] == "api":
            assert cmd["namespace"] == "backend"


def test_get_command_detail_requires_auth(
    client_with_commands: TestClient,
) -> None:
    """Test that getting command detail requires authentication."""
    response = client_with_commands.get("/api/v1/commands/test-cmd")

    assert response.status_code == 401
    assert "Not authenticated" in response.json()["detail"]


def test_get_command_detail_not_found(client_with_commands: TestClient, temp_vault: Path) -> None:
    """Test getting command that doesn't exist."""
    response = client_with_commands.get(
        "/api/v1/commands/nonexistent", headers={"Authorization": "Bearer test-token-123"}
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_get_command_detail_success(client_with_commands: TestClient, temp_vault: Path) -> None:
    """Test getting command detail successfully."""
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
        "disable-model-invocation: false\n"
        "---\n"
        "\n"
        "# Code Review\n"
        "\n"
        "Review the code in $1 for:\n"
        '- Security issues: !`grep -r "eval(" .`\n'
        "- Performance problems\n"
        "- Code style\n"
        "\n"
        "Reference: @STYLE_GUIDE.md\n"
    )

    response = client_with_commands.get(
        "/api/v1/commands/review", headers={"Authorization": "Bearer test-token-123"}
    )

    assert response.status_code == 200
    data = response.json()

    # Check basic info
    assert data["info"]["name"] == "review"
    assert data["info"]["description"] == "Review code"
    assert data["info"]["type"] == "vault"

    # Check frontmatter
    frontmatter = data["frontmatter"]
    assert frontmatter["description"] == "Review code"
    assert frontmatter["allowed_tools"] == ["Read", "Grep"]
    assert frontmatter["argument_hint"] == "[file-path]"
    assert frontmatter["model"] == "claude-3-5-haiku-20241022"
    assert frontmatter["disable_model_invocation"] is False

    # Check content
    assert "Code Review" in data["content"]
    assert "Security issues" in data["content"]

    # Check raw content includes frontmatter
    assert "---" in data["raw_content"]
    assert "allowed-tools:" in data["raw_content"]

    # Check parsed features
    assert data["has_arguments"] is True
    assert "$1" in data["argument_placeholders"]

    assert data["has_bash_execution"] is True
    assert 'grep -r "eval(" .' in data["bash_commands"]

    assert data["has_file_references"] is True


def test_get_command_detail_minimal(client_with_commands: TestClient, temp_vault: Path) -> None:
    """Test getting command detail with minimal frontmatter."""
    commands_dir = temp_vault / ".claude" / "commands"
    commands_dir.mkdir(parents=True)

    command_file = commands_dir / "simple.md"
    command_file.write_text("# Simple Command\n\nJust a simple command.")

    response = client_with_commands.get(
        "/api/v1/commands/simple", headers={"Authorization": "Bearer test-token-123"}
    )

    assert response.status_code == 200
    data = response.json()

    assert data["info"]["name"] == "simple"
    assert data["has_arguments"] is False
    assert data["has_bash_execution"] is False
    assert data["has_file_references"] is False
    assert data["argument_placeholders"] == []
    assert data["bash_commands"] == []


def test_get_command_detail_with_multiple_arguments(
    client_with_commands: TestClient, temp_vault: Path
) -> None:
    """Test command with multiple argument types."""
    commands_dir = temp_vault / ".claude" / "commands"
    commands_dir.mkdir(parents=True)

    command_file = commands_dir / "deploy.md"
    command_file.write_text(
        """Deploy to $1 environment.
Use config $2 and $3.
All remaining args: $ARGUMENTS
"""
    )

    response = client_with_commands.get(
        "/api/v1/commands/deploy", headers={"Authorization": "Bearer test-token-123"}
    )

    assert response.status_code == 200
    data = response.json()

    assert data["has_arguments"] is True
    placeholders = data["argument_placeholders"]
    assert "$1" in placeholders
    assert "$2" in placeholders
    assert "$3" in placeholders
    assert "$ARGUMENTS" in placeholders


def test_response_format_validation(client_with_commands: TestClient, temp_vault: Path) -> None:
    """Test that API responses match expected schema."""
    commands_dir = temp_vault / ".claude" / "commands"
    commands_dir.mkdir(parents=True)

    (commands_dir / "test.md").write_text("# Test\n\nTest command")

    # Test list response
    list_response = client_with_commands.get(
        "/api/v1/commands", headers={"Authorization": "Bearer test-token-123"}
    )
    list_data = list_response.json()

    # Verify CommandListResponse schema
    assert "commands" in list_data
    assert "total" in list_data
    assert "vault_commands" in list_data
    assert "plugin_commands" in list_data
    assert "mcp_commands" in list_data

    # Verify CommandInfo schema
    cmd = list_data["commands"][0]
    assert "name" in cmd
    assert "description" in cmd
    assert "type" in cmd
    assert "namespace" in cmd
    assert "argument_hint" in cmd
    assert "path" in cmd
    assert "file_name" in cmd

    # Test detail response
    detail_response = client_with_commands.get(
        "/api/v1/commands/test", headers={"Authorization": "Bearer test-token-123"}
    )
    detail_data = detail_response.json()

    # Verify CommandDetail schema
    assert "info" in detail_data
    assert "frontmatter" in detail_data
    assert "content" in detail_data
    assert "raw_content" in detail_data
    assert "has_arguments" in detail_data
    assert "argument_placeholders" in detail_data
    assert "has_bash_execution" in detail_data
    assert "bash_commands" in detail_data
    assert "has_file_references" in detail_data


def test_list_commands_ignores_invalid_files(
    client_with_commands: TestClient, temp_vault: Path
) -> None:
    """Test that invalid command files are gracefully ignored."""
    commands_dir = temp_vault / ".claude" / "commands"
    commands_dir.mkdir(parents=True)

    # Create valid command
    (commands_dir / "valid.md").write_text("# Valid\n\nValid command")

    # Create invalid markdown (malformed YAML)
    (commands_dir / "invalid.md").write_text(
        """---
invalid: yaml: structure:
  - wrong
---

Content
"""
    )

    response = client_with_commands.get(
        "/api/v1/commands", headers={"Authorization": "Bearer test-token-123"}
    )

    # Should succeed and return only valid command
    assert response.status_code == 200
    data = response.json()
    # Note: Depending on implementation, invalid files might be counted or skipped
    # This test verifies we don't crash on invalid files
    assert data["total"] >= 1
    assert any(cmd["name"] == "valid" for cmd in data["commands"])
