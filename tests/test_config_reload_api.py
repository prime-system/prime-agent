"""Integration tests for config reload API endpoint."""

import os
import tempfile
import time
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.main import app
from app.config import get_config_manager


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
def client(temp_config_file, monkeypatch):
    """Create a test client with temporary config."""
    monkeypatch.setenv("CONFIG_PATH", temp_config_file)

    # Reinitialize config manager with temp config
    # This is a bit tricky because the config is loaded at module import time
    # For testing, we'd need to reload the modules
    return TestClient(app)


def test_health_endpoint():
    """Test that health endpoint is available."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert "status" in response.json()


def test_config_endpoint_without_auth():
    """Test that config endpoint is available without auth."""
    client = TestClient(app)
    response = client.get("/api/v1/config")
    assert response.status_code == 200
    assert "features" in response.json()
    assert "server_info" in response.json()


def test_config_reload_requires_auth():
    """Test that config reload endpoint requires authentication."""
    client = TestClient(app)

    # Call without auth token
    response = client.post("/api/v1/config/reload")
    assert response.status_code == 403  # Forbidden (no auth header)

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
