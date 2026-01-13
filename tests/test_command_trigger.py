"""
Tests for command trigger and run status endpoints.

Tests cover:
- Triggering commands via API
- Polling run status and events
- Event buffering and cursor-based polling
- Authentication requirements
- Error handling (404, validation)
- Background task execution
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import commands
from app.models.command import CommandType
from app.services.agent import AgentService, ProcessResult
from app.services.command import CommandService
from app.services.command_run_manager import CommandRunManager, RunStatus
from app.services.container import ServiceContainer
from app.services.logs import LogService
from app.services.vault import VaultService


@pytest.fixture
def mock_command_service(temp_vault: Path) -> CommandService:
    """Create a real CommandService with temp vault."""
    # Create command files for testing
    commands_dir = temp_vault / ".claude" / "commands"
    commands_dir.mkdir(parents=True)

    (commands_dir / "test_cmd.md").write_text("# Test\n\nTest command")

    return CommandService(str(temp_vault))


@pytest.fixture
def mock_agent_service() -> AsyncMock:
    """Create a mock AgentService."""
    mock = AsyncMock(spec=AgentService)

    # Mock successful run_command
    async def mock_run_command(*args, **kwargs) -> ProcessResult:
        # Simulate event emission if handler provided
        event_handler = kwargs.get("event_handler")
        if event_handler:
            await event_handler("text", {"chunk": "Hello"})
            await event_handler("text", {"chunk": " world"})
            await event_handler(
                "complete", {"status": "success", "cost_usd": 0.01, "duration_ms": 100}
            )

        return {
            "success": True,
            "cost_usd": 0.01,
            "duration_ms": 100,
            "error": None,
        }

    mock.run_command = mock_run_command
    return mock


@pytest.fixture
def command_run_manager() -> CommandRunManager:
    """Create a real CommandRunManager."""
    return CommandRunManager(retention_minutes=60, max_events_per_run=200)


@pytest.fixture
def mock_container(
    mock_command_service: CommandService,
    mock_agent_service: AsyncMock,
    command_run_manager: CommandRunManager,
    temp_vault: Path,
) -> ServiceContainer:
    """Create a mock container with all required services."""
    container = MagicMock(spec=ServiceContainer)
    container.command_service = mock_command_service
    container.agent_service = mock_agent_service
    container.command_run_manager = command_run_manager
    vault_service = VaultService(str(temp_vault))
    vault_service.ensure_structure()
    container.vault_service = vault_service
    container.log_service = LogService(
        logs_dir=vault_service.logs_path(), vault_path=vault_service.vault_path
    )
    container.git_service = MagicMock()
    container.git_service.enabled = False
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


def test_trigger_command_requires_auth(client_with_commands: TestClient) -> None:
    """Test that triggering a command requires authentication."""
    response = client_with_commands.post(
        "/api/v1/commands/test_cmd/trigger",
        json={"arguments": None},
    )

    assert response.status_code == 401
    assert "Not authenticated" in response.json()["detail"]


def test_trigger_command_validates_name_format(client_with_commands: TestClient) -> None:
    """Test that command name validation rejects invalid formats."""
    # Test leading slash
    response = client_with_commands.post(
        "/api/v1/commands//test_cmd/trigger",
        json={"arguments": None},
        headers={"Authorization": "Bearer test-token-123"},
    )

    # FastAPI route matching will fail on leading slash
    assert response.status_code in (404, 422)

    # Test whitespace (if we had a way to inject it - would need URL encoding)
    # Actual validation happens in the endpoint


def test_trigger_nonexistent_command(client_with_commands: TestClient) -> None:
    """Test triggering a command that doesn't exist."""
    response = client_with_commands.post(
        "/api/v1/commands/nonexistent/trigger",
        json={"arguments": None},
        headers={"Authorization": "Bearer test-token-123"},
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_trigger_command_success(client_with_commands: TestClient) -> None:
    """Test successfully triggering a command."""
    response = client_with_commands.post(
        "/api/v1/commands/test_cmd/trigger",
        json={"arguments": "arg1 arg2"},
        headers={"Authorization": "Bearer test-token-123"},
    )

    assert response.status_code == 200
    data = response.json()

    assert "run_id" in data
    assert data["run_id"].startswith("cmdrun_")
    assert data["status"] == "started"
    assert "poll_url" in data
    assert data["run_id"] in data["poll_url"]


def test_trigger_command_without_arguments(client_with_commands: TestClient) -> None:
    """Test triggering a command without arguments."""
    response = client_with_commands.post(
        "/api/v1/commands/test_cmd/trigger",
        json={},
        headers={"Authorization": "Bearer test-token-123"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "run_id" in data


def test_get_run_status_requires_auth(client_with_commands: TestClient) -> None:
    """Test that getting run status requires authentication."""
    response = client_with_commands.get("/api/v1/commands/runs/cmdrun_123")

    assert response.status_code == 401
    assert "Not authenticated" in response.json()["detail"]


def test_get_run_status_not_found(client_with_commands: TestClient) -> None:
    """Test getting status for non-existent run."""
    response = client_with_commands.get(
        "/api/v1/commands/runs/cmdrun_nonexistent",
        headers={"Authorization": "Bearer test-token-123"},
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_run_status_success(client_with_commands: TestClient) -> None:
    """Test successfully getting run status with events."""
    # Trigger command
    trigger_response = client_with_commands.post(
        "/api/v1/commands/test_cmd/trigger",
        json={"arguments": "test"},
        headers={"Authorization": "Bearer test-token-123"},
    )

    assert trigger_response.status_code == 200
    run_id = trigger_response.json()["run_id"]

    # Wait a bit for background task to start
    await asyncio.sleep(0.1)

    # Get status
    status_response = client_with_commands.get(
        f"/api/v1/commands/runs/{run_id}",
        headers={"Authorization": "Bearer test-token-123"},
    )

    assert status_response.status_code == 200
    data = status_response.json()

    assert data["run_id"] == run_id
    assert data["command_name"] == "test_cmd"
    assert data["status"] in ("started", "running", "completed")
    assert "started_at" in data
    assert "events" in data
    assert "next_cursor" in data
    assert "dropped_before" in data


@pytest.mark.asyncio
async def test_polling_with_cursor(
    client_with_commands: TestClient,
    command_run_manager: CommandRunManager,
) -> None:
    """Test cursor-based polling for new events."""
    # Trigger command
    trigger_response = client_with_commands.post(
        "/api/v1/commands/test_cmd/trigger",
        json={},
        headers={"Authorization": "Bearer test-token-123"},
    )

    run_id = trigger_response.json()["run_id"]

    # Wait for events
    await asyncio.sleep(0.2)

    # First poll - get all events
    response1 = client_with_commands.get(
        f"/api/v1/commands/runs/{run_id}",
        headers={"Authorization": "Bearer test-token-123"},
    )

    data1 = response1.json()
    first_event_count = len(data1["events"])
    cursor = data1["next_cursor"]

    # Second poll with cursor - should get no new events (command completed)
    response2 = client_with_commands.get(
        f"/api/v1/commands/runs/{run_id}?after={cursor}",
        headers={"Authorization": "Bearer test-token-123"},
    )

    data2 = response2.json()
    assert len(data2["events"]) == 0  # No new events after cursor


@pytest.mark.asyncio
async def test_event_types_in_response(client_with_commands: TestClient) -> None:
    """Test that events contain expected types and structure."""
    # Trigger command
    trigger_response = client_with_commands.post(
        "/api/v1/commands/test_cmd/trigger",
        json={},
        headers={"Authorization": "Bearer test-token-123"},
    )

    run_id = trigger_response.json()["run_id"]

    # Wait for completion
    await asyncio.sleep(0.2)

    # Get status
    status_response = client_with_commands.get(
        f"/api/v1/commands/runs/{run_id}",
        headers={"Authorization": "Bearer test-token-123"},
    )

    data = status_response.json()
    events = data["events"]

    # Should have at least text and complete events
    event_types = {e["type"] for e in events}
    assert "text" in event_types
    assert "complete" in event_types

    # Verify event structure
    for event in events:
        assert "event_id" in event
        assert "type" in event


@pytest.mark.asyncio
async def test_command_run_manager_event_buffering() -> None:
    """Test CommandRunManager event buffering and eviction."""
    manager = CommandRunManager(retention_minutes=60, max_events_per_run=3)

    # Create run
    run_id = await manager.create_run("test")

    # Add more events than buffer size
    await manager.append_event(run_id, "text", {"chunk": "1"})
    await manager.append_event(run_id, "text", {"chunk": "2"})
    await manager.append_event(run_id, "text", {"chunk": "3"})
    await manager.append_event(run_id, "text", {"chunk": "4"})  # Should evict event 0

    # Get status
    status = await manager.get_run_status(run_id)
    assert status is not None

    # Should only have 3 events (buffer maxlen=3)
    assert len(status["events"]) == 3

    # First event should have been dropped
    assert status["dropped_before"] == 1

    # Remaining events should be 1, 2, 3
    event_ids = [e["event_id"] for e in status["events"]]
    assert event_ids == [1, 2, 3]


@pytest.mark.asyncio
async def test_command_run_manager_initial_cursor_includes_first_event() -> None:
    """Test that an initial empty poll doesn't skip the first event."""
    manager = CommandRunManager(retention_minutes=60, max_events_per_run=3)

    run_id = await manager.create_run("test")

    status = await manager.get_run_status(run_id)
    assert status is not None
    assert status["events"] == []
    assert status["next_cursor"] == -1

    await manager.append_event(run_id, "text", {"chunk": "first"})

    status_after = await manager.get_run_status(run_id, after_event_id=status["next_cursor"])
    event_ids = [e["event_id"] for e in status_after["events"]]
    assert event_ids == [0]


@pytest.mark.asyncio
async def test_command_run_manager_status_updates() -> None:
    """Test CommandRunManager status transitions."""
    manager = CommandRunManager()

    # Create run
    run_id = await manager.create_run("test")

    # Initially started
    status = await manager.get_run_status(run_id)
    assert status["status"] == "started"
    assert status["completed_at"] is None
    assert status["cost_usd"] is None

    # Update to running
    await manager.update_status(run_id, RunStatus.RUNNING)
    status = await manager.get_run_status(run_id)
    assert status["status"] == "running"

    # Update to completed
    await manager.update_status(
        run_id,
        RunStatus.COMPLETED,
        cost_usd=0.05,
        duration_ms=500,
    )
    status = await manager.get_run_status(run_id)
    assert status["status"] == "completed"
    assert status["completed_at"] is not None
    assert status["cost_usd"] == 0.05
    assert status["duration_ms"] == 500
    assert status["error"] is None


@pytest.mark.asyncio
async def test_command_run_manager_error_handling() -> None:
    """Test CommandRunManager error status."""
    manager = CommandRunManager()

    # Create run
    run_id = await manager.create_run("test")

    # Update to error
    await manager.update_status(
        run_id,
        RunStatus.ERROR,
        error="Something went wrong",
        cost_usd=0.02,
        duration_ms=100,
    )

    status = await manager.get_run_status(run_id)
    assert status["status"] == "error"
    assert status["error"] == "Something went wrong"
    assert status["completed_at"] is not None


@pytest.mark.asyncio
async def test_command_run_manager_cleanup_expired() -> None:
    """Test CommandRunManager cleanup of expired runs."""
    manager = CommandRunManager(retention_minutes=0)  # Expire immediately

    # Create run and complete it
    run_id = await manager.create_run("test")
    await manager.update_status(run_id, RunStatus.COMPLETED)

    # Should exist initially
    status = await manager.get_run_status(run_id)
    assert status is not None

    # Wait a moment and cleanup
    await asyncio.sleep(0.1)
    removed = await manager.cleanup_expired_runs()

    # Should be removed
    assert removed == 1
    status = await manager.get_run_status(run_id)
    assert status is None


@pytest.mark.asyncio
async def test_trigger_command_with_failed_agent() -> None:
    """Test triggering command when agent execution fails."""
    # Create mock agent that fails
    mock_agent = AsyncMock(spec=AgentService)

    async def failing_run_command(*args, **kwargs) -> ProcessResult:
        event_handler = kwargs.get("event_handler")
        if event_handler:
            await event_handler("error", {"error": "Agent failed", "isPermanent": True})

        return {
            "success": False,
            "cost_usd": None,
            "duration_ms": 50,
            "error": "Agent failed",
        }

    mock_agent.run_command = failing_run_command

    # Create test app with failing agent
    manager = CommandRunManager()
    commands_dir = Path("/tmp/test_vault/.claude/commands")
    commands_dir.mkdir(parents=True, exist_ok=True)
    (commands_dir / "test.md").write_text("# Test\n")

    command_service = CommandService("/tmp/test_vault")

    container = MagicMock(spec=ServiceContainer)
    container.command_service = command_service
    container.agent_service = mock_agent
    container.command_run_manager = manager

    from app.services import container as container_module

    original_get_container = container_module.get_container
    container_module.get_container = lambda: container

    try:
        app = FastAPI()
        app.include_router(commands.router)
        client = TestClient(app)

        # Trigger command
        response = client.post(
            "/api/v1/commands/test/trigger",
            json={},
            headers={"Authorization": "Bearer test-token-123"},
        )

        assert response.status_code == 200
        run_id = response.json()["run_id"]

        # Wait for execution
        await asyncio.sleep(0.2)

        # Check status
        status_response = client.get(
            f"/api/v1/commands/runs/{run_id}",
            headers={"Authorization": "Bearer test-token-123"},
        )

        data = status_response.json()
        assert data["status"] == "error"
        assert data["error"] == "Agent failed"

    finally:
        container_module.get_container = original_get_container


@pytest.mark.asyncio
async def test_active_run_count() -> None:
    """Test tracking active runs."""
    manager = CommandRunManager()

    # Initially no active runs
    count = await manager.get_active_run_count()
    assert count == 0

    # Create runs
    run1 = await manager.create_run("test1")
    run2 = await manager.create_run("test2")

    count = await manager.get_active_run_count()
    assert count == 2

    # Complete one run
    await manager.update_status(run1, RunStatus.COMPLETED)

    count = await manager.get_active_run_count()
    assert count == 1

    # Complete second run
    await manager.update_status(run2, RunStatus.COMPLETED)

    count = await manager.get_active_run_count()
    assert count == 0
