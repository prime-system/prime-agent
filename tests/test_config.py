"""Tests for YAML configuration loading and environment variable expansion."""

import os
import tempfile
from pathlib import Path

import pytest

from app.config import expand_env_vars, load_config_from_yaml, _build_settings_from_yaml


class TestExpandEnvVars:
    """Tests for environment variable expansion in configuration."""

    def test_expand_simple_env_var(self) -> None:
        """Test expansion of a single environment variable."""
        os.environ["TEST_VAR"] = "test_value"
        result = expand_env_vars("key: ${TEST_VAR}")
        assert result == "key: test_value"

    def test_expand_multiple_env_vars(self) -> None:
        """Test expansion of multiple environment variables."""
        os.environ["VAR1"] = "value1"
        os.environ["VAR2"] = "value2"
        result = expand_env_vars("first: ${VAR1}\nsecond: ${VAR2}")
        assert result == "first: value1\nsecond: value2"

    def test_expand_env_var_in_url(self) -> None:
        """Test expansion in a URL string."""
        os.environ["GITHUB_USER"] = "octocat"
        result = expand_env_vars("url: https://github.com/${GITHUB_USER}/repo.git")
        assert result == "url: https://github.com/octocat/repo.git"

    def test_missing_env_var_raises_error(self) -> None:
        """Test that missing environment variable raises KeyError."""
        with pytest.raises(KeyError) as exc_info:
            expand_env_vars("key: ${NONEXISTENT_VAR}")
        assert "NONEXISTENT_VAR" in str(exc_info.value)
        assert "not set" in str(exc_info.value)

    def test_no_env_vars_in_string(self) -> None:
        """Test that string without env vars is returned unchanged."""
        input_str = "key: value\nother: 123"
        result = expand_env_vars(input_str)
        assert result == input_str

    def test_env_var_with_special_chars(self) -> None:
        """Test expansion of env var containing special characters."""
        os.environ["API_KEY"] = "sk-ant-xxxx/yyyy+zzzz"
        result = expand_env_vars("key: ${API_KEY}")
        assert result == "key: sk-ant-xxxx/yyyy+zzzz"

    def test_env_var_with_newlines(self) -> None:
        """Test expansion of env var containing newlines (e.g., SSH key)."""
        ssh_key = "-----BEGIN OPENSSH PRIVATE KEY-----\nxxx\n-----END OPENSSH PRIVATE KEY-----"
        os.environ["SSH_KEY"] = ssh_key
        result = expand_env_vars("key: ${SSH_KEY}")
        assert result == f"key: {ssh_key}"


class TestLoadConfigFromYaml:
    """Tests for loading and parsing YAML configuration."""

    def test_load_valid_yaml_config(self) -> None:
        """Test loading a valid YAML configuration file."""
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
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
  model: claude-3-5-haiku-latest
  max_budget_usd: 2.0

git:
  enabled: false

logging:
  level: INFO
"""
            )

            config = load_config_from_yaml(str(config_path))
            assert config["vault"]["path"] == "/vault"
            assert config["auth"]["token"] == "test-token"
            assert config["anthropic"]["api_key"] == "sk-ant-test"
            assert config["anthropic"]["model"] == "claude-3-5-haiku-latest"
            assert config["git"]["enabled"] is False

    def test_missing_config_file_raises_error(self) -> None:
        """Test that missing config file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError) as exc_info:
            load_config_from_yaml("/nonexistent/path/config.yaml")
        assert "not found" in str(exc_info.value).lower()

    def test_invalid_yaml_raises_error(self) -> None:
        """Test that invalid YAML raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text("invalid: yaml: syntax: here:")

            with pytest.raises(ValueError, match="Invalid YAML") as exc_info:
                load_config_from_yaml(str(config_path))
            assert "Invalid YAML" in str(exc_info.value)

    def test_config_file_not_dict_raises_error(self) -> None:
        """Test that non-dict YAML root raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text("- item1\n- item2")

            with pytest.raises(ValueError, match="mapping/dictionary") as exc_info:
                load_config_from_yaml(str(config_path))
            assert "mapping/dictionary" in str(exc_info.value)

    def test_config_path_from_environment_variable(self) -> None:
        """Test that CONFIG_PATH environment variable is respected."""
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
        os.environ["AUTH_TOKEN"] = "test-token"

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "custom-config.yaml"
            config_path.write_text(
                """
vault:
  path: /vault
auth:
  token: ${AUTH_TOKEN}
anthropic:
  api_key: ${ANTHROPIC_API_KEY}
  model: claude-3-5-haiku-latest
git:
  enabled: false
logging:
  level: INFO
"""
            )

            os.environ["CONFIG_PATH"] = str(config_path)
            config = load_config_from_yaml()
            assert config["vault"]["path"] == "/vault"


class TestBuildSettingsFromYaml:
    """Tests for building Settings object from YAML configuration."""

    def test_build_settings_with_minimal_config(self) -> None:
        """Test building settings with minimal required configuration."""
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
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
  model: claude-3-5-haiku-latest

git:
  enabled: false

logging:
  level: INFO
"""
            )

            os.environ["CONFIG_PATH"] = str(config_path)
            settings = _build_settings_from_yaml()

            assert settings.vault_path == "/vault"
            assert settings.auth_token == "test-token"
            assert settings.anthropic_api_key == "sk-ant-test"
            assert settings.agent_model == "claude-3-5-haiku-latest"
            assert settings.git_enabled is False
            assert settings.log_level == "INFO"

    def test_build_settings_with_git_enabled(self) -> None:
        """Test building settings with Git enabled."""
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
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
  model: claude-3-5-haiku-latest

git:
  enabled: true
  repo_url: https://github.com/user/vault.git
  user_name: Prime Agent
  user_email: prime@local
  auth:
    method: https

logging:
  level: INFO
"""
            )

            os.environ["CONFIG_PATH"] = str(config_path)
            settings = _build_settings_from_yaml()

            assert settings.git_enabled is True
            assert settings.vault_repo_url == "https://github.com/user/vault.git"
            assert settings.git_user_name == "Prime Agent"
            assert settings.git_user_email == "prime@local"
            assert settings.git_auth_method == "https"

    def test_build_settings_git_enabled_without_repo_url_raises_error(self) -> None:
        """Test that git.enabled=true without repo_url raises error."""
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
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
  model: claude-3-5-haiku-latest

git:
  enabled: true
  repo_url: null

logging:
  level: INFO
"""
            )

            os.environ["CONFIG_PATH"] = str(config_path)
            with pytest.raises(ValueError, match="repo_url"):
                _build_settings_from_yaml()

    def test_build_settings_with_custom_api_endpoint(self) -> None:
        """Test building settings with custom Anthropic API endpoint."""
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
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
  base_url: https://custom.anthropic.com
  model: claude-3-5-haiku-latest

git:
  enabled: false

logging:
  level: DEBUG
"""
            )

            os.environ["CONFIG_PATH"] = str(config_path)
            settings = _build_settings_from_yaml()

            assert settings.anthropic_base_url == "https://custom.anthropic.com"
            assert settings.log_level == "DEBUG"

    def test_build_settings_with_budget_limit(self) -> None:
        """Test building settings with custom budget limit."""
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
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
  model: claude-3-5-sonnet-20241022
  max_budget_usd: 10.0

git:
  enabled: false

logging:
  level: INFO
"""
            )

            os.environ["CONFIG_PATH"] = str(config_path)
            settings = _build_settings_from_yaml()

            assert settings.agent_max_budget_usd == 10.0

    def test_missing_required_env_var_raises_error(self) -> None:
        """Test that missing required environment variable raises error."""
        # Ensure the var is not set
        os.environ.pop("ANTHROPIC_API_KEY", None)

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                """
vault:
  path: /vault

auth:
  token: test-token

anthropic:
  api_key: ${ANTHROPIC_API_KEY}
  model: claude-3-5-haiku-latest

git:
  enabled: false

logging:
  level: INFO
"""
            )

            os.environ["CONFIG_PATH"] = str(config_path)
            with pytest.raises((ValueError, KeyError)):
                _build_settings_from_yaml()
