"""Integration tests for config reload API endpoint."""

import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.command_run_manager import CommandRunManager


@pytest.fixture
def temp_config_file():
    """Create a temporary config file for API testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        config_path = f.name
        config = {
            "vault": {"path": "/vault"},
            "auth": {"token": "test-api-token"},
            "anthropic": {
                "api_key": "sk-test-key",
                "model": "claude-opus-4-5",
                "max_budget_usd": 1.0,
            },
            "logging": {"level": "INFO"},
        }
        yaml.dump(config, f)

    yield config_path

    # Cleanup
    Path(config_path).unlink(missing_ok=True)


@pytest.fixture
def test_app():
    """Create a test FastAPI app with config + health routers."""
    from app.api import config, health

    app = FastAPI(title="Prime Server Test")
    app.include_router(health.router)
    app.include_router(config.router)
    return app


@pytest.fixture
def client(temp_config_file, temp_vault, test_app, monkeypatch):
    """Create a test client with temporary config."""
    from app.services.agent_identity import AgentIdentityService
    from app.services.command import CommandService
    from app.services.container import init_container
    from app.services.health import HealthCheckService
    from app.services.inbox import InboxService
    from app.services.logs import LogService
    from app.services.push_notifications import PushNotificationService
    from app.services.relay_client import PrimePushRelayClient
    from app.services.schedule import ScheduleService
    from app.services.vault import VaultService

    monkeypatch.setenv("CONFIG_PATH", temp_config_file)

    vault_service = VaultService(str(temp_vault))
    vault_service.ensure_structure()
    health_service = HealthCheckService(
        vault_service=vault_service,
        git_service=MagicMock(),
        version="test-version",
    )
    command_service = CommandService(str(vault_service.vault_path))
    command_run_manager = CommandRunManager()
    agent_identity_service = MagicMock(spec=AgentIdentityService)
    agent_identity_service.get_cached_identity.return_value = "agent-123"

    init_container(
        vault_service=vault_service,
        git_service=MagicMock(),
        inbox_service=InboxService(),
        agent_service=MagicMock(),
        log_service=LogService(
            logs_dir=vault_service.logs_path(),
            vault_path=vault_service.vault_path,
            vault_service=vault_service,
        ),
        chat_session_manager=MagicMock(),
        agent_chat_service=MagicMock(),
        agent_session_manager=MagicMock(),
        push_notification_service=MagicMock(spec=PushNotificationService),
        relay_client=MagicMock(spec=PrimePushRelayClient),
        claude_session_api=MagicMock(),
        health_service=health_service,
        command_service=command_service,
        command_run_manager=command_run_manager,
        agent_identity_service=agent_identity_service,
        schedule_service=MagicMock(spec=ScheduleService),
    )

    with TestClient(test_app) as client:
        yield client


def test_health_endpoint(client):
    """Test that health endpoint is available."""
    response = client.get("/health")
    assert response.status_code == 200
    assert "status" in response.json()


def test_config_endpoint_requires_auth(client):
    """Test that config endpoint requires authentication."""
    response = client.get("/api/v1/config")
    assert response.status_code == 401


def test_config_reload_requires_auth(client):
    """Test that config reload endpoint requires authentication."""
    # Call without auth token
    response = client.post("/api/v1/config/reload")
    assert response.status_code == 401  # Unauthorized (no auth header)

    # Call with invalid auth token
    response = client.post(
        "/api/v1/config/reload",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert response.status_code == 401  # Unauthorized


def test_config_reload_endpoint_success():
    """Test successful config reload via API endpoint."""
    # This test would need proper setup with services initialized
    # For now, we document the expected behavior:
    # 1. POST /api/v1/config/reload with valid auth token
    # 2. Response should be 200 with success status
    # 3. Both config.yaml and .prime.yaml should be reloaded
    pass


def test_config_reload_with_vault_config_change():
    """Test that config reload picks up changes to .prime.yaml."""
    # This test would verify:
    # 1. Create vault with initial .prime.yaml
    # 2. Call config reload endpoint
    # 3. Modify .prime.yaml
    # 4. Call config reload endpoint again
    # 5. Verify new config is reflected in subsequent operations
    pass


def test_config_reload_preserves_config_on_error():
    """Test that config reload preserves valid config if reload fails."""
    # This test would verify:
    # 1. Make valid config reload via API
    # 2. Corrupt config file
    # 3. Call config reload endpoint
    # 4. Verify old valid config is still in use
    pass
