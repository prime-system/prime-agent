"""Type safety tests for configuration system."""

import pytest
from pydantic import ValidationError

# Import Settings directly to test its validation logic
# Note: This bypasses the module-level ConfigManager initialization
from app.config import Settings


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
