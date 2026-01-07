"""Tests for vault-specific configuration."""

from datetime import datetime
import time
from pathlib import Path

import pytest
import yaml

from app.models.vault_config import InboxConfig, VaultConfig, load_vault_config
from app.services.vault import VaultService


@pytest.fixture
def vault_with_config(temp_vault):
    """Create a vault with a .prime/settings.yaml config file."""

    def _create_config(config: dict):
        prime_dir = temp_vault / ".prime"
        prime_dir.mkdir(parents=True, exist_ok=True)
        config_file = prime_dir / "settings.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config, f)
        return temp_vault

    return _create_config


class TestVaultConfig:
    """Tests for VaultConfig model."""

    def test_default_config(self):
        """Default config uses .prime/inbox folder with weekly subfolders."""
        config = VaultConfig()
        assert config.inbox.folder == ".prime/inbox"
        assert config.inbox.weekly_subfolders is True
        assert config.logs.folder == ".prime/logs"

    def test_load_missing_config(self, temp_vault):
        """Missing .prime/settings.yaml returns default config."""
        config = load_vault_config(temp_vault)
        assert config.inbox.folder == ".prime/inbox"
        assert config.inbox.weekly_subfolders is True
        assert config.logs.folder == ".prime/logs"

    def test_load_empty_config(self, temp_vault):
        """Empty .prime/settings.yaml returns default config."""
        prime_dir = temp_vault / ".prime"
        prime_dir.mkdir(parents=True, exist_ok=True)
        (prime_dir / "settings.yaml").touch()
        config = load_vault_config(temp_vault)
        assert config.inbox.folder == ".prime/inbox"
        assert config.inbox.weekly_subfolders is True
        assert config.logs.folder == ".prime/logs"

    def test_load_custom_config(self, vault_with_config):
        """Load custom config with folder and subfolders."""
        vault = vault_with_config(
            {
                "inbox": {
                    "folder": "07-Inbox",
                    "weekly_subfolders": True,
                }
            }
        )
        config = load_vault_config(vault)
        assert config.inbox.folder == "07-Inbox"
        assert config.inbox.weekly_subfolders is True

    def test_load_custom_file_pattern(self, vault_with_config):
        """Load config with custom file pattern."""
        vault = vault_with_config(
            {
                "inbox": {
                    "file_pattern": "{year}-{month}-{day}_{hour}-{minute}-{second}_{source}.md",
                }
            }
        )
        config = load_vault_config(vault)
        assert (
            config.inbox.file_pattern == "{year}-{month}-{day}_{hour}-{minute}-{second}_{source}.md"
        )


class TestVaultServiceWithConfig:
    """Tests for VaultService with vault config."""

    def test_inbox_path_default(self, temp_vault):
        """Default inbox path is .prime/inbox."""
        service = VaultService(str(temp_vault))
        assert service.inbox_path() == temp_vault / ".prime" / "inbox"

    def test_inbox_path_custom(self, vault_with_config):
        """Custom inbox folder from config."""
        vault = vault_with_config({"inbox": {"folder": "07-Inbox"}})
        service = VaultService(str(vault))
        assert service.inbox_path() == vault / "07-Inbox"

    def test_get_capture_file_default(self, temp_vault):
        """Default config creates individual file per capture in weekly subfolders."""
        service = VaultService(str(temp_vault))
        dt = datetime(2025, 12, 21, 14, 30, 45)
        file_path = service.get_capture_file(dt, "iphone")
        assert file_path.name == "2025-12-21_14-30-45_iphone.md"
        assert file_path.parent.name == "2025-W51"
        assert file_path.parent.parent == temp_vault / ".prime" / "inbox"

    def test_get_capture_file_with_subfolders(self, vault_with_config):
        """Capture files organized in weekly subfolders."""
        vault = vault_with_config(
            {
                "inbox": {
                    "folder": "07-Inbox",
                    "weekly_subfolders": True,
                }
            }
        )
        service = VaultService(str(vault))
        dt = datetime(2025, 12, 21, 14, 30, 45)
        file_path = service.get_capture_file(dt, "iphone")
        assert file_path.name == "2025-12-21_14-30-45_iphone.md"
        assert file_path.parent.name == "2025-W51"
        assert file_path.parent.parent == vault / "07-Inbox"

    def test_get_capture_file_custom_pattern(self, vault_with_config):
        """Custom file pattern for captures."""
        vault = vault_with_config(
            {
                "inbox": {
                    "file_pattern": "capture_{iso_year}-W{iso_week}_{source}.md",
                }
            }
        )
        service = VaultService(str(vault))
        dt = datetime(2025, 12, 21, 14, 30, 45)
        file_path = service.get_capture_file(dt, "mac")
        assert file_path.name == "capture_2025-W51_mac.md"

    def test_get_capture_file_with_title_pattern(self, vault_with_config):
        """File pattern with {title} placeholder."""
        vault = vault_with_config(
            {
                "inbox": {
                    "file_pattern": "{title}.md",
                }
            }
        )
        service = VaultService(str(vault))
        dt = datetime(2025, 12, 21, 14, 30, 45)
        title = "meeting-notes"

        file_path = service.get_capture_file(dt, "iphone", title=title)

        assert file_path.name == "meeting-notes.md"

    def test_needs_title_generation_with_title_pattern(self, vault_with_config):
        """Detects when file pattern requires title generation."""
        vault = vault_with_config(
            {
                "inbox": {
                    "file_pattern": "{title}.md",
                }
            }
        )
        service = VaultService(str(vault))

        assert service.needs_title_generation() is True

    def test_needs_title_generation_without_title_pattern(self, vault_with_config):
        """Detects when file pattern doesn't require title generation."""
        vault = vault_with_config(
            {
                "inbox": {
                    "file_pattern": "{year}-{month}-{day}.md",
                }
            }
        )
        service = VaultService(str(vault))

        assert service.needs_title_generation() is False

    def test_reload_vault_config(self, vault_with_config):
        """Vault config can be reloaded."""
        vault = vault_with_config({"inbox": {"folder": "Inbox"}})
        service = VaultService(str(vault))

        # Initial config
        assert service.inbox_path() == vault / "Inbox"

        # Update config file
        config_file = vault / ".prime" / "settings.yaml"
        time.sleep(0.01)
        with open(config_file, "w") as f:
            yaml.dump({"inbox": {"folder": "07-Inbox"}}, f)

        # Config reloads on access when file changes
        assert service.inbox_path() == vault / "07-Inbox"

        # After reload, returns new value
        service.reload_vault_config()
        assert service.inbox_path() == vault / "07-Inbox"
