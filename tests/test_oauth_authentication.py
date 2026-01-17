"""Tests for OAuth token authentication support."""

import os
import tempfile
from pathlib import Path

import pytest

from app.config import _build_settings_from_yaml
from app.services.agent import AgentService
from app.services.agent_chat import AgentChatService


class TestOAuthTokenConfiguration:
    """Tests for OAuth token configuration in settings."""

    def test_build_settings_with_oauth_token(self) -> None:
        """Test building settings with OAuth token instead of API key."""
        os.environ.pop("ANTHROPIC_API_KEY", None)  # Ensure API key is not set
        os.environ["ANTHROPIC_OAUTH_TOKEN"] = "test-oauth-token"
        os.environ["AUTH_TOKEN"] = "test-token"

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                """
vault:
  path: /vault

auth:
  token: ${AUTH_TOKEN}

anthropic:
  oauth_token: ${ANTHROPIC_OAUTH_TOKEN}
  model: claude-3-5-haiku-latest

git:
  enabled: false

logging:
  level: INFO
"""
            )

            os.environ["CONFIG_PATH"] = str(config_path)
            settings = _build_settings_from_yaml()

            assert settings.anthropic_oauth_token == "test-oauth-token"
            assert settings.anthropic_api_key is None
            assert settings.auth_token == "test-token"
            assert settings.agent_model == "claude-3-5-haiku-latest"

    def test_build_settings_with_both_api_key_and_oauth_token_raises_error(self) -> None:
        """Test that setting both api_key and oauth_token raises error."""
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
        os.environ["ANTHROPIC_OAUTH_TOKEN"] = "test-oauth-token"
        os.environ["AUTH_TOKEN"] = "test-token"

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                """
vault:
  path: /vault

auth:
  token: ${AUTH_TOKEN}

anthropic:
  api_key: ${ANTHROPIC_API_KEY}
  oauth_token: ${ANTHROPIC_OAUTH_TOKEN}
  model: claude-3-5-haiku-latest

git:
  enabled: false

logging:
  level: INFO
"""
            )

            os.environ["CONFIG_PATH"] = str(config_path)
            with pytest.raises(
                ValueError, match="Both ANTHROPIC_API_KEY and ANTHROPIC_OAUTH_TOKEN"
            ):
                _build_settings_from_yaml()

    def test_build_settings_with_neither_api_key_nor_oauth_token_raises_error(self) -> None:
        """Test that missing both api_key and oauth_token raises error."""
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("ANTHROPIC_OAUTH_TOKEN", None)
        os.environ["AUTH_TOKEN"] = "test-token"

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                """
vault:
  path: /vault

auth:
  token: ${AUTH_TOKEN}

anthropic:
  model: claude-3-5-haiku-latest

git:
  enabled: false

logging:
  level: INFO
"""
            )

            os.environ["CONFIG_PATH"] = str(config_path)
            with pytest.raises(
                ValueError, match="Either ANTHROPIC_API_KEY or ANTHROPIC_OAUTH_TOKEN"
            ):
                _build_settings_from_yaml()

    def test_build_settings_with_oauth_token_and_base_url(self) -> None:
        """Test building settings with OAuth token and custom base URL."""
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ["ANTHROPIC_OAUTH_TOKEN"] = "test-oauth-token"
        os.environ["AUTH_TOKEN"] = "test-token"

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                """
vault:
  path: /vault

auth:
  token: ${AUTH_TOKEN}

anthropic:
  oauth_token: ${ANTHROPIC_OAUTH_TOKEN}
  base_url: https://custom.anthropic.com
  model: claude-3-5-haiku-latest

git:
  enabled: false

logging:
  level: INFO
"""
            )

            os.environ["CONFIG_PATH"] = str(config_path)
            settings = _build_settings_from_yaml()

            assert settings.anthropic_oauth_token == "test-oauth-token"
            assert settings.anthropic_base_url == "https://custom.anthropic.com"
            assert settings.anthropic_api_key is None


class TestAgentServiceOAuthToken:
    """Tests for AgentService with OAuth token."""

    def test_agent_service_with_oauth_token(self) -> None:
        """Test AgentService initialization with OAuth token."""
        service = AgentService(
            vault_path="/vault",
            oauth_token="test-oauth-token",
            max_budget_usd=2.0,
        )

        assert service.oauth_token == "test-oauth-token"
        assert service.api_key is None
        assert service.vault_path == Path("/vault")

    def test_agent_service_with_api_key(self) -> None:
        """Test AgentService initialization with API key (traditional)."""
        service = AgentService(
            vault_path="/vault",
            api_key="sk-ant-test",
            max_budget_usd=2.0,
        )

        assert service.api_key == "sk-ant-test"
        assert service.oauth_token is None
        assert service.vault_path == Path("/vault")

    def test_agent_service_with_both_raises_error(self) -> None:
        """Test that providing both api_key and oauth_token raises error."""
        with pytest.raises(ValueError, match="Only one of api_key or oauth_token"):
            AgentService(
                vault_path="/vault",
                api_key="sk-ant-test",
                oauth_token="test-oauth-token",
                max_budget_usd=2.0,
            )

    def test_agent_service_with_neither_raises_error(self) -> None:
        """Test that providing neither api_key nor oauth_token raises error."""
        with pytest.raises(ValueError, match="Either api_key or oauth_token"):
            AgentService(
                vault_path="/vault",
                max_budget_usd=2.0,
            )

    def test_agent_service_oauth_token_in_agent_options(self) -> None:
        """Test that OAuth token is passed correctly to ClaudeAgentOptions."""
        service = AgentService(
            vault_path="/vault",
            oauth_token="test-oauth-token",
            max_budget_usd=2.0,
        )

        options = service._build_agent_options()

        # Verify OAuth token is in env dict
        assert "CLAUDE_CODE_OAUTH_TOKEN" in options.env
        assert options.env["CLAUDE_CODE_OAUTH_TOKEN"] == "test-oauth-token"
        # Verify API key is NOT in env dict
        assert "ANTHROPIC_API_KEY" not in options.env

    def test_agent_service_api_key_in_agent_options(self) -> None:
        """Test that API key is passed correctly to ClaudeAgentOptions."""
        service = AgentService(
            vault_path="/vault",
            api_key="sk-ant-test",
            max_budget_usd=2.0,
        )

        options = service._build_agent_options()

        # Verify API key is in env dict
        assert "ANTHROPIC_API_KEY" in options.env
        assert options.env["ANTHROPIC_API_KEY"] == "sk-ant-test"
        # Verify OAuth token is NOT in env dict
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in options.env


class TestAgentChatServiceOAuthToken:
    """Tests for AgentChatService with OAuth token."""

    def test_agent_chat_service_with_oauth_token(self) -> None:
        """Test AgentChatService initialization with OAuth token."""
        service = AgentChatService(
            vault_path="/vault",
            model="claude-3-5-haiku-latest",
            oauth_token="test-oauth-token",
        )

        assert service.oauth_token == "test-oauth-token"
        assert service.api_key is None
        assert service.vault_path == Path("/vault")
        assert service.model == "claude-3-5-haiku-latest"

    def test_agent_chat_service_with_api_key(self) -> None:
        """Test AgentChatService initialization with API key (traditional)."""
        service = AgentChatService(
            vault_path="/vault",
            model="claude-3-5-haiku-latest",
            api_key="sk-ant-test",
        )

        assert service.api_key == "sk-ant-test"
        assert service.oauth_token is None
        assert service.vault_path == Path("/vault")

    def test_agent_chat_service_with_both_raises_error(self) -> None:
        """Test that providing both api_key and oauth_token raises error."""
        with pytest.raises(ValueError, match="Only one of api_key or oauth_token"):
            AgentChatService(
                vault_path="/vault",
                model="claude-3-5-haiku-latest",
                api_key="sk-ant-test",
                oauth_token="test-oauth-token",
            )

    def test_agent_chat_service_with_neither_raises_error(self) -> None:
        """Test that providing neither api_key nor oauth_token raises error."""
        with pytest.raises(ValueError, match="Either api_key or oauth_token"):
            AgentChatService(
                vault_path="/vault",
                model="claude-3-5-haiku-latest",
            )

    def test_agent_chat_service_oauth_token_in_agent_options(self) -> None:
        """Test that OAuth token is passed correctly to ClaudeAgentOptions."""
        service = AgentChatService(
            vault_path="/vault",
            model="claude-3-5-haiku-latest",
            oauth_token="test-oauth-token",
        )

        options = service._create_agent_options()

        # Verify OAuth token is in env dict
        assert "CLAUDE_CODE_OAUTH_TOKEN" in options.env
        assert options.env["CLAUDE_CODE_OAUTH_TOKEN"] == "test-oauth-token"
        # Verify API key is NOT in env dict
        assert "ANTHROPIC_API_KEY" not in options.env

    def test_agent_chat_service_api_key_in_agent_options(self) -> None:
        """Test that API key is passed correctly to ClaudeAgentOptions."""
        service = AgentChatService(
            vault_path="/vault",
            model="claude-3-5-haiku-latest",
            api_key="sk-ant-test",
        )

        options = service._create_agent_options()

        # Verify API key is in env dict
        assert "ANTHROPIC_API_KEY" in options.env
        assert options.env["ANTHROPIC_API_KEY"] == "sk-ant-test"
        # Verify OAuth token is NOT in env dict
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in options.env
