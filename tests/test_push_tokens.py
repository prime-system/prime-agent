"""Unit tests for push_tokens service."""

import json
from pathlib import Path

import pytest

from app.services.push_tokens import (
    add_or_update_token,
    load_tokens,
    remove_token,
    sanitize_device_name,
    save_tokens,
    validate_token_format,
)


class TestValidateTokenFormat:
    """Test token format validation."""

    def test_valid_token_lowercase(self):
        """Valid token with lowercase hex."""
        assert validate_token_format("a" * 64)

    def test_valid_token_uppercase(self):
        """Valid token with uppercase hex."""
        assert validate_token_format("A" * 64)

    def test_valid_token_mixed(self):
        """Valid token with mixed case hex."""
        assert validate_token_format("aB" * 32)

    def test_valid_token_numbers(self):
        """Valid token with numbers."""
        assert validate_token_format("0123456789abcdef" * 4)

    def test_invalid_token_too_short(self):
        """Invalid: too short."""
        assert not validate_token_format("a" * 63)

    def test_invalid_token_too_long(self):
        """Invalid: too long."""
        assert not validate_token_format("a" * 65)

    def test_invalid_token_non_hex(self):
        """Invalid: non-hex characters."""
        assert not validate_token_format("g" * 64)

    def test_invalid_token_spaces(self):
        """Invalid: contains spaces."""
        assert not validate_token_format("a" * 32 + " " + "a" * 31)

    def test_invalid_token_empty(self):
        """Invalid: empty string."""
        assert not validate_token_format("")


class TestSanitizeDeviceName:
    """Test device name sanitization."""

    def test_valid_name(self):
        """Valid device name."""
        assert sanitize_device_name("michaels-iphone") == "michaels-iphone"

    def test_name_with_spaces(self):
        """Name with spaces."""
        assert sanitize_device_name("Michael's iPhone") == "Michaels iPhone"

    def test_name_with_apostrophe(self):
        """Name with apostrophe (allowed)."""
        # Note: apostrophe is removed by our regex
        assert sanitize_device_name("Sarah's iPad") == "Sarahs iPad"

    def test_name_with_underscore(self):
        """Name with underscore."""
        assert sanitize_device_name("work_macbook") == "work_macbook"

    def test_name_with_path_separator(self):
        """Name with path separator (removed)."""
        assert sanitize_device_name("../../etc/passwd") == "etcpasswd"

    def test_name_with_control_chars(self):
        """Name with control characters (removed)."""
        assert sanitize_device_name("test\x00\x1fdevice") == "testdevice"

    def test_name_with_special_chars(self):
        """Name with special characters (removed)."""
        assert sanitize_device_name("device@#$%!") == "device"

    def test_name_with_multiple_spaces(self):
        """Name with multiple spaces (collapsed)."""
        assert sanitize_device_name("my    device") == "my device"

    def test_name_too_long(self):
        """Name exceeding max length (truncated)."""
        long_name = "a" * 100
        result = sanitize_device_name(long_name)
        assert result
        assert len(result) == 64

    def test_name_empty_after_sanitization(self):
        """Name becomes empty after sanitization."""
        assert sanitize_device_name("@#$%") is None

    def test_name_none(self):
        """None input."""
        assert sanitize_device_name(None) is None

    def test_name_empty_string(self):
        """Empty string input."""
        assert sanitize_device_name("") is None


class TestLoadTokens:
    """Test token loading."""

    def test_load_nonexistent_file(self, tmp_path: Path):
        """Load from nonexistent file returns empty structure."""
        tokens_file = tmp_path / "tokens.json"
        result = load_tokens(tokens_file)
        assert result == {"devices": []}

    def test_load_valid_file(self, tmp_path: Path):
        """Load from valid file."""
        tokens_file = tmp_path / "tokens.json"
        data = {
            "devices": [
                {
                    "token": "a" * 64,
                    "device_type": "iphone",
                    "device_name": "test-device",
                    "registered_at": "2025-12-28T10:00:00Z",
                    "last_seen": "2025-12-28T10:00:00Z",
                    "environment": "production",
                }
            ]
        }
        tokens_file.write_text(json.dumps(data))

        result = load_tokens(tokens_file)
        assert result == data

    def test_load_file_missing_devices_key(self, tmp_path: Path):
        """Load from file missing 'devices' key."""
        tokens_file = tmp_path / "tokens.json"
        tokens_file.write_text(json.dumps({}))

        result = load_tokens(tokens_file)
        assert result == {"devices": []}

    def test_load_invalid_json(self, tmp_path: Path):
        """Load from file with invalid JSON."""
        tokens_file = tmp_path / "tokens.json"
        tokens_file.write_text("not valid json")

        result = load_tokens(tokens_file)
        assert result == {"devices": []}


class TestSaveTokens:
    """Test token saving."""

    def test_save_to_new_file(self, tmp_path: Path):
        """Save to new file."""
        tokens_file = tmp_path / "subdir" / "tokens.json"
        data = {"devices": []}

        save_tokens(tokens_file, data)

        assert tokens_file.exists()
        assert json.loads(tokens_file.read_text()) == data

    def test_save_creates_parent_dir(self, tmp_path: Path):
        """Save creates parent directory if needed."""
        tokens_file = tmp_path / "a" / "b" / "c" / "tokens.json"
        data = {"devices": []}

        save_tokens(tokens_file, data)

        assert tokens_file.exists()
        assert tokens_file.parent.exists()

    def test_save_overwrites_existing(self, tmp_path: Path):
        """Save overwrites existing file."""
        tokens_file = tmp_path / "tokens.json"
        old_data = {"devices": [{"token": "old"}]}
        new_data = {"devices": [{"token": "new"}]}

        tokens_file.write_text(json.dumps(old_data))
        save_tokens(tokens_file, new_data)

        assert json.loads(tokens_file.read_text()) == new_data

    def test_save_sets_permissions(self, tmp_path: Path):
        """Save sets secure file permissions."""
        tokens_file = tmp_path / "tokens.json"
        data = {"devices": []}

        save_tokens(tokens_file, data)

        # Check permissions (0o600 = rw-------)
        assert tokens_file.stat().st_mode & 0o777 == 0o600


class TestAddOrUpdateToken:
    """Test token addition and updating."""

    def test_add_new_token(self, tmp_path: Path):
        """Add new token."""
        tokens_file = tmp_path / "tokens.json"
        token = "a" * 64

        add_or_update_token(
            tokens_file=tokens_file,
            token=token,
            device_type="iphone",
            device_name="test-device",
            environment="production",
        )

        data = json.loads(tokens_file.read_text())
        assert len(data["devices"]) == 1
        assert data["devices"][0]["token"] == token
        assert data["devices"][0]["device_type"] == "iphone"
        assert data["devices"][0]["device_name"] == "test-device"
        assert data["devices"][0]["environment"] == "production"
        assert "registered_at" in data["devices"][0]
        assert "last_seen" in data["devices"][0]

    def test_add_token_with_none_device_name(self, tmp_path: Path):
        """Add token with None device_name."""
        tokens_file = tmp_path / "tokens.json"
        token = "b" * 64

        add_or_update_token(
            tokens_file=tokens_file,
            token=token,
            device_type="ipad",
            device_name=None,
            environment="development",
        )

        data = json.loads(tokens_file.read_text())
        assert data["devices"][0]["device_name"] is None

    def test_update_existing_token(self, tmp_path: Path):
        """Update existing token."""
        tokens_file = tmp_path / "tokens.json"
        token = "c" * 64

        # Add initial token
        add_or_update_token(
            tokens_file=tokens_file,
            token=token,
            device_type="iphone",
            device_name="old-name",
            environment="production",
        )

        data = json.loads(tokens_file.read_text())
        original_registered_at = data["devices"][0]["registered_at"]

        # Update same token
        add_or_update_token(
            tokens_file=tokens_file,
            token=token,
            device_type="ipad",
            device_name="new-name",
            environment="development",
        )

        data = json.loads(tokens_file.read_text())
        assert len(data["devices"]) == 1  # Still only one device
        assert data["devices"][0]["token"] == token
        assert data["devices"][0]["device_type"] == "ipad"
        assert data["devices"][0]["device_name"] == "new-name"
        assert data["devices"][0]["environment"] == "development"
        assert data["devices"][0]["registered_at"] == original_registered_at
        assert data["devices"][0]["last_seen"] != original_registered_at

    def test_add_invalid_token_format(self, tmp_path: Path):
        """Add token with invalid format raises ValueError."""
        tokens_file = tmp_path / "tokens.json"

        with pytest.raises(ValueError, match="Invalid token format"):
            add_or_update_token(
                tokens_file=tokens_file,
                token="invalid",
                device_type="iphone",
                device_name="test",
                environment="production",
            )

    def test_add_multiple_tokens(self, tmp_path: Path):
        """Add multiple different tokens."""
        tokens_file = tmp_path / "tokens.json"

        add_or_update_token(
            tokens_file=tokens_file,
            token="a" * 64,
            device_type="iphone",
            device_name="device1",
            environment="production",
        )

        add_or_update_token(
            tokens_file=tokens_file,
            token="b" * 64,
            device_type="ipad",
            device_name="device2",
            environment="production",
        )

        data = json.loads(tokens_file.read_text())
        assert len(data["devices"]) == 2


class TestRemoveToken:
    """Test token removal."""

    def test_remove_existing_token(self, tmp_path: Path):
        """Remove existing token."""
        tokens_file = tmp_path / "tokens.json"
        token = "d" * 64

        # Add token
        add_or_update_token(
            tokens_file=tokens_file,
            token=token,
            device_type="iphone",
            device_name="test",
            environment="production",
        )

        # Remove token
        removed = remove_token(tokens_file, token)

        assert removed is True
        data = json.loads(tokens_file.read_text())
        assert len(data["devices"]) == 0

    def test_remove_nonexistent_token(self, tmp_path: Path):
        """Remove nonexistent token."""
        tokens_file = tmp_path / "tokens.json"
        tokens_file.write_text(json.dumps({"devices": []}))

        removed = remove_token(tokens_file, "e" * 64)

        assert removed is False

    def test_remove_one_of_many_tokens(self, tmp_path: Path):
        """Remove one token from multiple."""
        tokens_file = tmp_path / "tokens.json"
        token1 = "f" * 64
        token2 = "g" * 64

        # Add two tokens
        add_or_update_token(
            tokens_file=tokens_file,
            token=token1,
            device_type="iphone",
            device_name="device1",
            environment="production",
        )
        add_or_update_token(
            tokens_file=tokens_file,
            token=token2,
            device_type="ipad",
            device_name="device2",
            environment="production",
        )

        # Remove first token
        removed = remove_token(tokens_file, token1)

        assert removed is True
        data = json.loads(tokens_file.read_text())
        assert len(data["devices"]) == 1
        assert data["devices"][0]["token"] == token2
