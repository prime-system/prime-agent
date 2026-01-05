"""Tests for VaultService dynamic config reloading."""

import tempfile
import time
from pathlib import Path

import pytest
import yaml

from app.services.vault import VaultService


@pytest.fixture
def temp_vault_dir():
    """Create a temporary vault directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vault_path = Path(tmpdir)
        yield vault_path


def test_vault_service_loads_vault_config(temp_vault_dir):
    """Test that VaultService loads vault config from .prime/settings.yaml."""
    # Create .prime/settings.yaml
    prime_dir = temp_vault_dir / ".prime"
    prime_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "inbox": {
            "folder": "Inbox",
            "weekly_subfolders": True,
            "file_pattern": "{year}-{month}-{day}_{title}.md",
        }
    }
    with open(prime_dir / "settings.yaml", "w") as f:
        yaml.dump(config, f)

    service = VaultService(str(temp_vault_dir))
    vault_config = service.vault_config

    assert vault_config.inbox.folder == "Inbox"
    assert vault_config.inbox.weekly_subfolders is True
    assert vault_config.inbox.file_pattern == "{year}-{month}-{day}_{title}.md"


def test_vault_service_uses_defaults_if_no_config(temp_vault_dir):
    """Test that VaultService uses default config if .prime/settings.yaml doesn't exist."""
    service = VaultService(str(temp_vault_dir))
    vault_config = service.vault_config

    # Should use defaults
    assert vault_config.inbox.folder == ".prime/inbox"
    assert vault_config.inbox.weekly_subfolders is True


def test_vault_service_detects_vault_config_changes(temp_vault_dir):
    """Test that VaultService detects when .prime/settings.yaml has changed."""
    # Create initial .prime/settings.yaml
    prime_dir = temp_vault_dir / ".prime"
    prime_dir.mkdir(parents=True, exist_ok=True)
    config1 = {
        "inbox": {
            "folder": "Inbox",
            "weekly_subfolders": True,
            "file_pattern": "{year}-{month}-{day}_{title}.md",
        }
    }
    with open(prime_dir / "settings.yaml", "w") as f:
        yaml.dump(config1, f)

    service = VaultService(str(temp_vault_dir))
    vault_config1 = service.vault_config
    assert vault_config1.inbox.folder == "Inbox"

    # Wait to ensure mtime is different
    time.sleep(0.01)

    # Modify .prime/settings.yaml
    config2 = {
        "inbox": {
            "folder": "MyInbox",
            "weekly_subfolders": False,
            "file_pattern": "{source}-{title}.md",
        }
    }
    with open(prime_dir / "settings.yaml", "w") as f:
        yaml.dump(config2, f)

    # Access vault_config again - should detect change and reload
    vault_config2 = service.vault_config
    assert vault_config2.inbox.folder == "MyInbox"
    assert vault_config2.inbox.weekly_subfolders is False
    assert vault_config2.inbox.file_pattern == "{source}-{title}.md"


def test_vault_service_force_reload(temp_vault_dir):
    """Test that VaultService.reload_vault_config() forces immediate reload."""
    # Create initial .prime/settings.yaml
    prime_dir = temp_vault_dir / ".prime"
    prime_dir.mkdir(parents=True, exist_ok=True)
    config1 = {
        "inbox": {
            "folder": "Inbox",
            "weekly_subfolders": True,
        }
    }
    with open(prime_dir / "settings.yaml", "w") as f:
        yaml.dump(config1, f)

    service = VaultService(str(temp_vault_dir))
    vault_config1 = service.vault_config
    assert vault_config1.inbox.folder == "Inbox"

    # Modify .prime/settings.yaml
    time.sleep(0.01)
    config2 = {
        "inbox": {
            "folder": "CustomInbox",
            "weekly_subfolders": False,
        }
    }
    with open(prime_dir / "settings.yaml", "w") as f:
        yaml.dump(config2, f)

    # Force reload
    service.reload_vault_config()
    vault_config2 = service.vault_config
    assert vault_config2.inbox.folder == "CustomInbox"
    assert vault_config2.inbox.weekly_subfolders is False


def test_vault_service_handles_invalid_yaml(temp_vault_dir):
    """Test that VaultService handles invalid YAML gracefully."""
    # Create initial valid .prime/settings.yaml
    prime_dir = temp_vault_dir / ".prime"
    prime_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "inbox": {
            "folder": "Inbox",
            "weekly_subfolders": True,
        }
    }
    with open(prime_dir / "settings.yaml", "w") as f:
        yaml.dump(config, f)

    service = VaultService(str(temp_vault_dir))
    vault_config1 = service.vault_config
    assert vault_config1.inbox.folder == "Inbox"

    # Write invalid YAML
    time.sleep(0.01)
    with open(prime_dir / "settings.yaml", "w") as f:
        f.write("invalid: yaml: [broken")

    # Get vault_config - should still return last valid config
    vault_config2 = service.vault_config
    assert vault_config2.inbox.folder == "Inbox"  # Still valid


def test_vault_service_handles_missing_config_file(temp_vault_dir):
    """Test that VaultService handles missing .prime/settings.yaml gracefully."""
    # Create initial .prime/settings.yaml
    prime_dir = temp_vault_dir / ".prime"
    prime_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "inbox": {
            "folder": "Inbox",
            "weekly_subfolders": True,
        }
    }
    with open(prime_dir / "settings.yaml", "w") as f:
        yaml.dump(config, f)

    service = VaultService(str(temp_vault_dir))
    vault_config1 = service.vault_config
    assert vault_config1.inbox.folder == "Inbox"

    # Delete the file
    (prime_dir / "settings.yaml").unlink()

    # Get vault_config - should still return last valid config or use default
    vault_config2 = service.vault_config
    assert vault_config2.inbox.folder == "Inbox"  # Still valid


def test_vault_service_no_reload_if_file_unchanged(temp_vault_dir):
    """Test that VaultService doesn't reload if file hasn't changed."""
    # Create .prime/settings.yaml
    prime_dir = temp_vault_dir / ".prime"
    prime_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "inbox": {
            "folder": "Inbox",
            "weekly_subfolders": True,
        }
    }
    with open(prime_dir / "settings.yaml", "w") as f:
        yaml.dump(config, f)

    service = VaultService(str(temp_vault_dir))

    # Access vault_config multiple times
    vault_config1 = service.vault_config
    vault_config2 = service.vault_config
    vault_config3 = service.vault_config

    # Should all be the same instance (no reload)
    assert vault_config1 is vault_config2
    assert vault_config2 is vault_config3


def test_vault_service_file_created_at_runtime(temp_vault_dir):
    """Test that VaultService detects .prime/settings.yaml created at runtime."""
    # Start without .prime/settings.yaml
    service = VaultService(str(temp_vault_dir))
    vault_config1 = service.vault_config

    # Should use defaults
    assert vault_config1.inbox.folder == ".prime/inbox"

    # Create .prime/settings.yaml at runtime
    time.sleep(0.01)
    prime_dir = temp_vault_dir / ".prime"
    prime_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "inbox": {
            "folder": "MyInbox",
            "weekly_subfolders": False,
        }
    }
    with open(prime_dir / "settings.yaml", "w") as f:
        yaml.dump(config, f)

    time.sleep(0.01)

    # Access vault_config - should detect new file and load it
    vault_config2 = service.vault_config
    assert vault_config2.inbox.folder == "MyInbox"
    assert vault_config2.inbox.weekly_subfolders is False


def test_vault_service_file_deleted_and_recreated(temp_vault_dir):
    """Test that VaultService handles .prime/settings.yaml deletion and recreation."""
    # Create initial .prime/settings.yaml
    prime_dir = temp_vault_dir / ".prime"
    prime_dir.mkdir(parents=True, exist_ok=True)
    config1 = {
        "inbox": {
            "folder": "Inbox",
            "weekly_subfolders": True,
        }
    }
    with open(prime_dir / "settings.yaml", "w") as f:
        yaml.dump(config1, f)

    service = VaultService(str(temp_vault_dir))
    vault_config1 = service.vault_config
    assert vault_config1.inbox.folder == "Inbox"

    # Delete file
    (prime_dir / "settings.yaml").unlink()
    time.sleep(0.01)

    # Should still return previous valid config
    vault_config2 = service.vault_config
    assert vault_config2.inbox.folder == "Inbox"

    # Recreate with different config
    time.sleep(0.01)
    config3 = {
        "inbox": {
            "folder": "NewInbox",
            "weekly_subfolders": False,
        }
    }
    with open(prime_dir / "settings.yaml", "w") as f:
        yaml.dump(config3, f)

    time.sleep(0.01)

    # Should detect recreated file and load new config
    vault_config3 = service.vault_config
    assert vault_config3.inbox.folder == "NewInbox"
    assert vault_config3.inbox.weekly_subfolders is False
