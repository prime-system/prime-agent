"""Tests for the /api/v1/config endpoint."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def mock_settings():
    """Create a mock Settings object."""
    settings = MagicMock()
    settings.git_enabled = False
    settings.workspaces_enabled = False
    return settings


@pytest.fixture
def test_app():
    """Create a test FastAPI app with config router."""
    from app.api import config

    app = FastAPI(title="Prime Server Test")
    app.include_router(config.router)
    return app


@pytest.fixture
def temp_vault():
    """Create a temporary vault directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vault_path = Path(tmpdir) / "vault"
        vault_path.mkdir()
        yield vault_path


@pytest.fixture
def client(temp_vault, test_app, mock_settings):
    """Test client with vault service and settings initialized."""
    from app.api import config
    from app.services.vault import VaultService

    vault_service = VaultService(str(temp_vault))
    vault_service.ensure_structure()
    config.init_services(vault_service, mock_settings)

    with TestClient(test_app) as c:
        yield c


class TestConfigEndpoint:
    """Tests for the /api/v1/config endpoint."""

    def test_config_endpoint_returns_correct_structure(self, client):
        """Test that config endpoint returns the expected JSON structure."""
        response = client.get("/api/v1/config")
        assert response.status_code == 200

        data = response.json()
        assert "features" in data
        assert "server_info" in data

        # Check features structure
        features = data["features"]
        assert "git_enabled" in features
        assert "workspaces_enabled" in features
        assert "custom_process_prompt" in features

        # Check that removed fields are NOT in response
        assert "processing_enabled" not in features
        assert "version" not in features

        # Check server_info structure
        server_info = data["server_info"]
        assert "name" in server_info
        assert "version" in server_info

    def test_config_with_git_enabled(self, client, mock_settings):
        """Test config when git is enabled in settings."""
        mock_settings.git_enabled = True

        response = client.get("/api/v1/config")
        assert response.status_code == 200

        data = response.json()
        assert data["features"]["git_enabled"] is True

    def test_config_with_git_disabled(self, client, mock_settings):
        """Test config when git is disabled in settings."""
        mock_settings.git_enabled = False

        response = client.get("/api/v1/config")
        assert response.status_code == 200

        data = response.json()
        assert data["features"]["git_enabled"] is False

    def test_config_with_custom_prompt(self, client, temp_vault):
        """Test config when user has created processCapture.md in vault."""
        # Create custom command in vault
        commands_dir = temp_vault / ".claude" / "commands"
        commands_dir.mkdir(parents=True, exist_ok=True)
        (commands_dir / "processCapture.md").write_text("# Custom prompt")

        response = client.get("/api/v1/config")
        assert response.status_code == 200

        data = response.json()
        assert data["features"]["custom_process_prompt"] is True

    def test_config_without_custom_prompt(self, client, temp_vault):
        """Test config when no vault file exists (using default template)."""
        # Ensure no vault file exists
        custom_path = temp_vault / ".claude" / "commands" / "processCapture.md"
        if custom_path.exists():
            custom_path.unlink()

        response = client.get("/api/v1/config")
        assert response.status_code == 200

        data = response.json()
        assert data["features"]["custom_process_prompt"] is False

    def test_config_workspaces_enabled(self, client, mock_settings):
        """Test config when workspaces are enabled in settings."""
        mock_settings.workspaces_enabled = True

        response = client.get("/api/v1/config")
        assert response.status_code == 200

        data = response.json()
        assert data["features"]["workspaces_enabled"] is True

    def test_config_workspaces_disabled(self, client, mock_settings):
        """Test config when workspaces are disabled in settings."""
        mock_settings.workspaces_enabled = False

        response = client.get("/api/v1/config")
        assert response.status_code == 200

        data = response.json()
        assert data["features"]["workspaces_enabled"] is False

    def test_config_server_info(self, client):
        """Test server_info fields."""
        response = client.get("/api/v1/config")
        assert response.status_code == 200

        data = response.json()
        assert data["server_info"]["name"] == "Prime"
        # Version comes from pyproject.toml
        assert data["server_info"]["version"] == "0.1.0"

    def test_config_full_scenario_all_features_enabled(
        self, client, temp_vault, mock_settings
    ):
        """Test config with all features enabled."""
        # Enable git and workspaces in settings
        mock_settings.git_enabled = True
        mock_settings.workspaces_enabled = True

        # Create custom processCapture in vault
        commands_dir = temp_vault / ".claude" / "commands"
        commands_dir.mkdir(parents=True, exist_ok=True)
        (commands_dir / "processCapture.md").write_text("# Custom prompt")

        response = client.get("/api/v1/config")
        assert response.status_code == 200

        data = response.json()
        assert data["features"]["git_enabled"] is True
        assert data["features"]["custom_process_prompt"] is True
        assert data["features"]["workspaces_enabled"] is True
        assert data["server_info"]["name"] == "Prime"
        assert data["server_info"]["version"] == "0.1.0"

    def test_config_full_scenario_all_features_disabled(self, client, mock_settings):
        """Test config with all features disabled."""
        mock_settings.git_enabled = False
        mock_settings.workspaces_enabled = False

        response = client.get("/api/v1/config")
        assert response.status_code == 200

        data = response.json()
        assert data["features"]["git_enabled"] is False
        assert data["features"]["custom_process_prompt"] is False
        assert data["features"]["workspaces_enabled"] is False
