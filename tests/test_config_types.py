"""Type safety tests for configuration system."""

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

# Import Settings directly to test its validation logic
# Note: This bypasses the module-level ConfigManager initialization
from app.config import Settings


class TestAPNsValidation:
    """Test APNs configuration validation."""

    def test_apn_disabled_fields_can_be_none(self) -> None:
        """When apn_enabled=false, APNs fields can be None."""
        settings = Settings(
            auth_token="test-token",
            anthropic_api_key="sk-ant-test",
            agent_model="claude-3-5-sonnet",
            apn_enabled=False,
            apple_team_id=None,
            apple_bundle_id=None,
            apple_key_id=None,
            apple_p8_key=None,
        )
        assert settings.apn_enabled is False
        assert settings.apple_team_id is None
        assert settings.apple_bundle_id is None
        assert settings.apple_key_id is None
        assert settings.apple_p8_key is None

    def test_apn_enabled_requires_team_id(self) -> None:
        """When apn_enabled=true, team_id is required."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                auth_token="test-token",
                anthropic_api_key="sk-ant-test",
                agent_model="claude-3-5-sonnet",
                apn_enabled=True,
                apple_team_id=None,  # ❌ Required when enabled
                apple_bundle_id="com.example.app",
                apple_key_id="ABC123",
                apple_p8_key="-----BEGIN PRIVATE KEY-----\n...",
            )
        assert "apple_team_id" in str(exc_info.value)

    def test_apn_enabled_requires_bundle_id(self) -> None:
        """When apn_enabled=true, bundle_id is required."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                auth_token="test-token",
                anthropic_api_key="sk-ant-test",
                agent_model="claude-3-5-sonnet",
                apn_enabled=True,
                apple_team_id="TEAM123",
                apple_bundle_id=None,  # ❌ Required when enabled
                apple_key_id="ABC123",
                apple_p8_key="-----BEGIN PRIVATE KEY-----\n...",
            )
        assert "apple_bundle_id" in str(exc_info.value)

    def test_apn_enabled_requires_key_id(self) -> None:
        """When apn_enabled=true, key_id is required."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                auth_token="test-token",
                anthropic_api_key="sk-ant-test",
                agent_model="claude-3-5-sonnet",
                apn_enabled=True,
                apple_team_id="TEAM123",
                apple_bundle_id="com.example.app",
                apple_key_id=None,  # ❌ Required when enabled
                apple_p8_key="-----BEGIN PRIVATE KEY-----\n...",
            )
        assert "apple_key_id" in str(exc_info.value)

    def test_apn_enabled_requires_p8_key(self) -> None:
        """When apn_enabled=true, p8_key is required."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                auth_token="test-token",
                anthropic_api_key="sk-ant-test",
                agent_model="claude-3-5-sonnet",
                apn_enabled=True,
                apple_team_id="TEAM123",
                apple_bundle_id="com.example.app",
                apple_key_id="ABC123",
                apple_p8_key=None,  # ❌ Required when enabled
            )
        assert "apple_p8_key" in str(exc_info.value)

    def test_apn_enabled_with_all_fields(self) -> None:
        """When apn_enabled=true and all fields provided, validation passes."""
        settings = Settings(
            auth_token="test-token",
            anthropic_api_key="sk-ant-test",
            agent_model="claude-3-5-sonnet",
            apn_enabled=True,
            apple_team_id="TEAM123",
            apple_bundle_id="com.example.app",
            apple_key_id="ABC123",
            apple_p8_key="-----BEGIN PRIVATE KEY-----\nMIGfMA0GCSqGSIb3D...",
        )
        # After validation, mypy knows these are str, not str | None
        assert isinstance(settings.apple_team_id, str)
        assert isinstance(settings.apple_bundle_id, str)
        assert isinstance(settings.apple_key_id, str)
        assert isinstance(settings.apple_p8_key, str)


class TestGitValidation:
    """Test Git configuration validation."""

    def test_git_disabled_url_can_be_none(self) -> None:
        """When git_enabled=false, repo_url can be None."""
        settings = Settings(
            auth_token="test-token",
            anthropic_api_key="sk-ant-test",
            agent_model="claude-3-5-sonnet",
            git_enabled=False,
            vault_repo_url=None,
        )
        assert settings.git_enabled is False
        assert settings.vault_repo_url is None

    def test_git_enabled_requires_repo_url(self) -> None:
        """When git_enabled=true, repo_url is required."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                auth_token="test-token",
                anthropic_api_key="sk-ant-test",
                agent_model="claude-3-5-sonnet",
                git_enabled=True,
                vault_repo_url=None,  # ❌ Required when enabled
            )
        assert "vault_repo_url" in str(exc_info.value)

    def test_git_enabled_with_repo_url(self) -> None:
        """When git_enabled=true and repo_url provided, validation passes."""
        settings = Settings(
            auth_token="test-token",
            anthropic_api_key="sk-ant-test",
            agent_model="claude-3-5-sonnet",
            git_enabled=True,
            vault_repo_url="git@github.com:example/repo.git",
        )
        assert isinstance(settings.vault_repo_url, str)


class TestSettingsInitialization:
    """Test Settings object can be initialized without type: ignore."""

    def test_settings_initialization_with_minimal_config(self) -> None:
        """Settings can be initialized with minimal required fields."""
        settings = Settings(
            auth_token="test-token",
            anthropic_api_key="sk-ant-test",
            agent_model="claude-3-5-sonnet",
        )
        assert settings is not None
        assert isinstance(settings, Settings)

    def test_settings_initialization_with_git_enabled(self) -> None:
        """Settings can be initialized with git enabled without type: ignore."""
        settings = Settings(
            auth_token="test-token",
            anthropic_api_key="sk-ant-test",
            agent_model="claude-3-5-sonnet",
            git_enabled=True,
            vault_repo_url="git@github.com:example/repo.git",
        )
        assert settings.git_enabled is True
        assert settings.vault_repo_url is not None

    def test_settings_initialization_with_apn_enabled(self) -> None:
        """Settings can be initialized with APNs enabled without type: ignore."""
        settings = Settings(
            auth_token="test-token",
            anthropic_api_key="sk-ant-test",
            agent_model="claude-3-5-sonnet",
            apn_enabled=True,
            apple_team_id="TEAM123",
            apple_bundle_id="com.example.app",
            apple_key_id="ABC123",
            apple_p8_key="-----BEGIN PRIVATE KEY-----\ntest...",
        )
        assert settings.apn_enabled is True
        # Type narrowing: mypy knows these are str when apn_enabled=True
        assert settings.apple_team_id is not None
        assert settings.apple_bundle_id is not None
        assert settings.apple_key_id is not None
        assert settings.apple_p8_key is not None
