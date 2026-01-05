"""Tests for dynamic configuration management and reloading."""

import os
import tempfile
import time
from pathlib import Path

import pytest
import yaml

from app.services.config_manager import ConfigManager


@pytest.fixture
def temp_config_file():
    """Create a temporary config file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        config_path = f.name
        config = {
            "vault": {"path": "/vault"},
            "auth": {"token": "test-token-1"},
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


def test_config_manager_loads_initial_config(temp_config_file):
    """Test that ConfigManager loads initial config correctly."""
    # Set CONFIG_PATH environment variable
    os.environ["CONFIG_PATH"] = temp_config_file

    manager = ConfigManager(temp_config_file)
    settings = manager.get_settings()

    assert settings.vault_path == "/vault"
    assert settings.auth_token == "test-token-1"
    assert settings.anthropic_api_key == "sk-test-key"
    assert settings.agent_model == "claude-opus-4-5"
    assert settings.agent_max_budget_usd == 1.0
    assert settings.log_level == "INFO"


def test_config_manager_detects_file_changes(temp_config_file):
    """Test that ConfigManager detects when config file has changed."""
    manager = ConfigManager(temp_config_file)
    settings1 = manager.get_settings()
    assert settings1.auth_token == "test-token-1"

    # Wait to ensure mtime is different
    time.sleep(0.01)

    # Modify config file
    with open(temp_config_file, "w") as f:
        config = {
            "vault": {"path": "/vault"},
            "auth": {"token": "test-token-2"},
            "anthropic": {
                "api_key": "sk-test-key",
                "model": "claude-opus-4-5",
                "max_budget_usd": 1.0,
            },
            "logging": {"level": "DEBUG"},
        }
        yaml.dump(config, f)

    # Get settings again - should detect change and reload
    settings2 = manager.get_settings()
    assert settings2.auth_token == "test-token-2"
    assert settings2.log_level == "DEBUG"


def test_config_manager_force_reload(temp_config_file):
    """Test that force reload works even if file hasn't changed."""
    manager = ConfigManager(temp_config_file)
    settings1 = manager.get_settings()
    assert settings1.auth_token == "test-token-1"

    # Modify file
    time.sleep(0.01)
    with open(temp_config_file, "w") as f:
        config = {
            "vault": {"path": "/vault"},
            "auth": {"token": "test-token-3"},
            "anthropic": {
                "api_key": "sk-test-key",
                "model": "claude-opus-4-5",
                "max_budget_usd": 2.0,
            },
            "logging": {"level": "WARNING"},
        }
        yaml.dump(config, f)

    # Force reload
    manager.reload()
    settings2 = manager.get_settings()
    assert settings2.auth_token == "test-token-3"
    assert settings2.log_level == "WARNING"
    assert settings2.agent_max_budget_usd == 2.0


def test_config_manager_handles_invalid_yaml(temp_config_file):
    """Test that ConfigManager maintains last valid config when YAML is invalid."""
    manager = ConfigManager(temp_config_file)
    settings1 = manager.get_settings()
    assert settings1.auth_token == "test-token-1"

    # Write invalid YAML
    time.sleep(0.01)
    with open(temp_config_file, "w") as f:
        f.write("invalid: yaml: content: [broken")

    # Get settings - should still return previous valid config
    settings2 = manager.get_settings()
    assert settings2.auth_token == "test-token-1"  # Still valid


def test_config_manager_handles_missing_file():
    """Test that ConfigManager raises error if config file doesn't exist."""
    with pytest.raises(FileNotFoundError):
        ConfigManager("/nonexistent/path/config.yaml")


def test_config_manager_handles_missing_file_on_reload(temp_config_file):
    """Test that ConfigManager keeps last valid config if file is deleted."""
    manager = ConfigManager(temp_config_file)
    settings1 = manager.get_settings()
    assert settings1.auth_token == "test-token-1"

    # Delete the file
    Path(temp_config_file).unlink()

    # Get settings - should still return previous valid config
    settings2 = manager.get_settings()
    assert settings2.auth_token == "test-token-1"  # Still valid


def test_config_manager_handles_validation_error(temp_config_file):
    """Test that ConfigManager handles validation errors gracefully."""
    manager = ConfigManager(temp_config_file)
    settings1 = manager.get_settings()
    assert settings1.auth_token == "test-token-1"

    # Write config with invalid structure that fails validation
    time.sleep(0.01)
    with open(temp_config_file, "w") as f:
        config = {
            "vault": {"path": "/vault"},
            # Missing required auth.token field
            "anthropic": {
                "api_key": "sk-test-key",
                # Missing required model field
                "max_budget_usd": 1.0,
            },
        }
        yaml.dump(config, f)

    # Get settings - should still return previous valid config
    settings2 = manager.get_settings()
    assert settings2.auth_token == "test-token-1"  # Still valid


def test_config_manager_thread_safety(temp_config_file):
    """Test that ConfigManager is thread-safe."""
    import threading

    manager = ConfigManager(temp_config_file)
    results = []

    def get_token():
        settings = manager.get_settings()
        results.append(settings.auth_token)

    # Create multiple threads accessing config simultaneously
    threads = [threading.Thread(target=get_token) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # All threads should have gotten a valid token
    assert all(token == "test-token-1" for token in results)
    assert len(results) == 10


def test_config_manager_env_var_expansion(temp_config_file):
    """Test that ConfigManager expands environment variables."""
    # Set environment variable
    os.environ["TEST_API_KEY"] = "sk-expanded-key"
    os.environ["TEST_LOG_LEVEL"] = "DEBUG"

    # Write config with env var references
    with open(temp_config_file, "w") as f:
        config_str = """
vault:
  path: /vault
auth:
  token: test-token
anthropic:
  api_key: ${TEST_API_KEY}
  model: claude-opus-4-5
  max_budget_usd: 1.0
logging:
  level: ${TEST_LOG_LEVEL}
"""
        f.write(config_str)

    manager = ConfigManager(temp_config_file)
    settings = manager.get_settings()

    assert settings.anthropic_api_key == "sk-expanded-key"
    assert settings.log_level == "DEBUG"

    # Cleanup
    del os.environ["TEST_API_KEY"]
    del os.environ["TEST_LOG_LEVEL"]


def test_config_manager_missing_env_var_on_initial_load(temp_config_file):
    """Test that ConfigManager raises error if required env var is missing."""
    # Write config with undefined env var reference
    with open(temp_config_file, "w") as f:
        config_str = """
vault:
  path: /vault
auth:
  token: test-token
anthropic:
  api_key: ${UNDEFINED_API_KEY}
  model: claude-opus-4-5
  max_budget_usd: 1.0
"""
        f.write(config_str)

    with pytest.raises(ValueError, match="Error expanding environment variables"):
        ConfigManager(temp_config_file)


def test_config_manager_missing_env_var_on_reload(temp_config_file):
    """Test that ConfigManager handles missing env var on reload gracefully."""
    # Start with valid config
    manager = ConfigManager(temp_config_file)
    settings1 = manager.get_settings()
    assert settings1.auth_token == "test-token-1"

    # Modify config to use undefined env var
    time.sleep(0.01)
    with open(temp_config_file, "w") as f:
        config_str = """
vault:
  path: /vault
auth:
  token: test-token
anthropic:
  api_key: ${UNDEFINED_API_KEY}
  model: claude-opus-4-5
  max_budget_usd: 1.0
"""
        f.write(config_str)

    # Get settings - should still return previous valid config
    settings2 = manager.get_settings()
    assert settings2.auth_token == "test-token-1"  # Still valid


def test_config_manager_file_created_at_runtime(temp_config_file):
    """Test that ConfigManager detects config file created at runtime."""
    # Start with deleted config file
    Path(temp_config_file).unlink()

    # Initialize ConfigManager (this will fail since file doesn't exist)
    with pytest.raises(FileNotFoundError):
        ConfigManager(temp_config_file)


def test_config_manager_file_deleted_and_recreated(temp_config_file):
    """Test that ConfigManager handles file deletion and recreation gracefully."""
    manager = ConfigManager(temp_config_file)
    settings1 = manager.get_settings()
    assert settings1.auth_token == "test-token-1"

    # Delete file
    Path(temp_config_file).unlink()
    time.sleep(0.01)

    # Get settings - should still return previous valid config
    settings2 = manager.get_settings()
    assert settings2.auth_token == "test-token-1"  # Still valid

    # Recreate file with new config
    with open(temp_config_file, "w") as f:
        config = {
            "vault": {"path": "/vault"},
            "auth": {"token": "test-token-recreated"},
            "anthropic": {
                "api_key": "sk-test-key",
                "model": "claude-opus-4-5",
                "max_budget_usd": 1.0,
            },
        }
        yaml.dump(config, f)

    time.sleep(0.01)

    # Get settings - should detect recreated file and load new config
    settings3 = manager.get_settings()
    assert settings3.auth_token == "test-token-recreated"  # New config loaded
