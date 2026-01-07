"""Unit tests for device_registry service."""

import json
from pathlib import Path

import pytest

from app.services.device_registry import (
    Device,
    DeviceRegistry,
    add_or_update_device,
    get_device,
    init_file_lock,
    list_devices,
    load_devices,
    remove_device,
    sanitize_device_name,
    save_devices,
)


@pytest.fixture(autouse=True)
async def setup_file_lock():
    """Initialize file lock before each async test."""
    await init_file_lock()


class TestSanitizeDeviceName:
    """Test device name sanitization."""

    def test_valid_name(self):
        """Valid device name."""
        assert sanitize_device_name("michaels-iphone") == "michaels-iphone"

    def test_name_with_spaces(self):
        """Name with spaces."""
        assert sanitize_device_name("Michael's iPhone") == "Michael's iPhone"

    def test_name_with_apostrophe(self):
        """Name with apostrophe (allowed)."""
        # Note: apostrophe is allowed by our regex
        assert sanitize_device_name("Sarah's iPad") == "Sarah's iPad"

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


class TestLoadDevices:
    """Test device loading."""

    def test_load_nonexistent_file(self, tmp_path: Path):
        """Load from nonexistent file returns empty structure."""
        devices_file = tmp_path / "devices.json"
        result = load_devices(devices_file)
        assert isinstance(result, DeviceRegistry)
        assert result.devices == []

    def test_load_valid_file(self, tmp_path: Path):
        """Load from valid file."""
        devices_file = tmp_path / "devices.json"
        data = {
            "devices": [
                {
                    "installation_id": "550e8400-e29b-41d4-a716-446655440000",
                    "device_name": "test-device",
                    "device_type": "iphone",
                    "push_url": "https://example.com/push/abc123",
                    "registered_at": "2025-12-28T10:00:00Z",
                    "last_seen": "2025-12-28T10:00:00Z",
                }
            ]
        }
        devices_file.write_text(json.dumps(data))

        result = load_devices(devices_file)
        assert isinstance(result, DeviceRegistry)
        assert len(result.devices) == 1
        assert result.devices[0].installation_id == "550e8400-e29b-41d4-a716-446655440000"

    def test_load_file_missing_devices_key(self, tmp_path: Path):
        """Load from file missing 'devices' key."""
        devices_file = tmp_path / "devices.json"
        devices_file.write_text(json.dumps({}))

        result = load_devices(devices_file)
        assert isinstance(result, DeviceRegistry)
        assert result.devices == []

    def test_load_invalid_json(self, tmp_path: Path):
        """Load from file with invalid JSON."""
        devices_file = tmp_path / "devices.json"
        devices_file.write_text("not valid json")

        result = load_devices(devices_file)
        assert isinstance(result, DeviceRegistry)
        assert result.devices == []


class TestSaveDevices:
    """Test device saving."""

    def test_save_to_new_file(self, tmp_path: Path):
        """Save to new file."""
        devices_file = tmp_path / "subdir" / "devices.json"
        registry = DeviceRegistry(devices=[])

        save_devices(devices_file, registry)

        assert devices_file.exists()
        assert json.loads(devices_file.read_text()) == {"devices": []}

    def test_save_creates_parent_dir(self, tmp_path: Path):
        """Save creates parent directory if needed."""
        devices_file = tmp_path / "a" / "b" / "c" / "devices.json"
        registry = DeviceRegistry(devices=[])

        save_devices(devices_file, registry)

        assert devices_file.exists()
        assert devices_file.parent.exists()

    def test_save_overwrites_existing(self, tmp_path: Path):
        """Save overwrites existing file."""
        devices_file = tmp_path / "devices.json"
        old_data = {"devices": []}
        new_device = Device(
            installation_id="550e8400-e29b-41d4-a716-446655440000",
            device_name="new-device",
            device_type="iphone",
            push_url="https://example.com/push/new",
            registered_at="2025-12-28T10:00:00Z",
            last_seen="2025-12-28T10:00:00Z",
        )
        new_registry = DeviceRegistry(devices=[new_device])

        devices_file.write_text(json.dumps(old_data))
        save_devices(devices_file, new_registry)

        data = json.loads(devices_file.read_text())
        assert len(data["devices"]) == 1
        assert data["devices"][0]["installation_id"] == "550e8400-e29b-41d4-a716-446655440000"

    def test_save_sets_permissions(self, tmp_path: Path):
        """Save sets secure file permissions."""
        devices_file = tmp_path / "devices.json"
        registry = DeviceRegistry(devices=[])

        save_devices(devices_file, registry)

        # Check permissions (0o600 = rw-------)
        assert devices_file.stat().st_mode & 0o777 == 0o600


class TestAddOrUpdateDevice:
    """Test device addition and updating."""

    @pytest.mark.asyncio
    async def test_add_new_device(self, tmp_path: Path):
        """Add new device."""
        devices_file = tmp_path / "devices.json"
        installation_id = "550e8400-e29b-41d4-a716-446655440000"

        await add_or_update_device(
            devices_file=devices_file,
            installation_id=installation_id,
            device_name="test-device",
            device_type="iphone",
            push_url="https://example.com/push/abc123",
        )

        data = json.loads(devices_file.read_text())
        assert len(data["devices"]) == 1
        assert data["devices"][0]["installation_id"] == installation_id
        assert data["devices"][0]["device_type"] == "iphone"
        assert data["devices"][0]["device_name"] == "test-device"
        assert data["devices"][0]["push_url"] == "https://example.com/push/abc123"
        assert "registered_at" in data["devices"][0]
        assert "last_seen" in data["devices"][0]

    @pytest.mark.asyncio
    async def test_add_device_with_none_device_name(self, tmp_path: Path):
        """Add device with None device_name."""
        devices_file = tmp_path / "devices.json"
        installation_id = "550e8400-e29b-41d4-a716-446655440001"

        await add_or_update_device(
            devices_file=devices_file,
            installation_id=installation_id,
            device_name=None,
            device_type="ipad",
            push_url="https://example.com/push/xyz789",
        )

        data = json.loads(devices_file.read_text())
        assert data["devices"][0]["device_name"] is None

    @pytest.mark.asyncio
    async def test_update_existing_device(self, tmp_path: Path):
        """Update existing device."""
        devices_file = tmp_path / "devices.json"
        installation_id = "550e8400-e29b-41d4-a716-446655440002"

        # Add initial device
        await add_or_update_device(
            devices_file=devices_file,
            installation_id=installation_id,
            device_name="old-name",
            device_type="iphone",
            push_url="https://example.com/push/old",
        )

        data = json.loads(devices_file.read_text())
        original_registered_at = data["devices"][0]["registered_at"]

        # Update same device
        await add_or_update_device(
            devices_file=devices_file,
            installation_id=installation_id,
            device_name="new-name",
            device_type="ipad",
            push_url="https://example.com/push/new",
        )

        data = json.loads(devices_file.read_text())
        assert len(data["devices"]) == 1  # Still only one device
        assert data["devices"][0]["installation_id"] == installation_id
        assert data["devices"][0]["device_type"] == "ipad"
        assert data["devices"][0]["device_name"] == "new-name"
        assert data["devices"][0]["push_url"] == "https://example.com/push/new"
        assert data["devices"][0]["registered_at"] == original_registered_at
        assert data["devices"][0]["last_seen"] != original_registered_at

    @pytest.mark.asyncio
    async def test_update_device_name_only(self, tmp_path: Path):
        """Update device name without changing push_url."""
        devices_file = tmp_path / "devices.json"
        installation_id = "550e8400-e29b-41d4-a716-446655440010"
        original_push_url = "https://example.com/push/original"

        # Add initial device
        await add_or_update_device(
            devices_file=devices_file,
            installation_id=installation_id,
            device_name="old-name",
            device_type="iphone",
            push_url=original_push_url,
        )

        # Update only device name (push_url=None)
        await add_or_update_device(
            devices_file=devices_file,
            installation_id=installation_id,
            device_name="new-name",
            device_type="iphone",
            push_url=None,
        )

        data = json.loads(devices_file.read_text())
        assert len(data["devices"]) == 1
        assert data["devices"][0]["device_name"] == "new-name"
        assert data["devices"][0]["push_url"] == original_push_url  # Preserved

    @pytest.mark.asyncio
    async def test_new_device_requires_push_url(self, tmp_path: Path):
        """Raise ValueError when creating new device without push_url."""
        devices_file = tmp_path / "devices.json"
        installation_id = "550e8400-e29b-41d4-a716-446655440011"

        # Attempt to add new device without push_url
        with pytest.raises(ValueError, match="push_url is required"):
            await add_or_update_device(
                devices_file=devices_file,
                installation_id=installation_id,
                device_name="test",
                device_type="iphone",
                push_url=None,
            )

        # Verify device was not created
        assert not devices_file.exists()

    @pytest.mark.asyncio
    async def test_add_multiple_devices(self, tmp_path: Path):
        """Add multiple different devices."""
        devices_file = tmp_path / "devices.json"

        await add_or_update_device(
            devices_file=devices_file,
            installation_id="550e8400-e29b-41d4-a716-446655440003",
            device_name="device1",
            device_type="iphone",
            push_url="https://example.com/push/device1",
        )

        await add_or_update_device(
            devices_file=devices_file,
            installation_id="550e8400-e29b-41d4-a716-446655440004",
            device_name="device2",
            device_type="ipad",
            push_url="https://example.com/push/device2",
        )

        data = json.loads(devices_file.read_text())
        assert len(data["devices"]) == 2


class TestRemoveDevice:
    """Test device removal."""

    @pytest.mark.asyncio
    async def test_remove_existing_device(self, tmp_path: Path):
        """Remove existing device."""
        devices_file = tmp_path / "devices.json"
        installation_id = "550e8400-e29b-41d4-a716-446655440005"

        # Add device
        await add_or_update_device(
            devices_file=devices_file,
            installation_id=installation_id,
            device_name="test",
            device_type="iphone",
            push_url="https://example.com/push/test",
        )

        # Remove device
        removed = await remove_device(devices_file, installation_id)

        assert removed is True
        data = json.loads(devices_file.read_text())
        assert len(data["devices"]) == 0

    @pytest.mark.asyncio
    async def test_remove_nonexistent_device(self, tmp_path: Path):
        """Remove nonexistent device."""
        devices_file = tmp_path / "devices.json"
        devices_file.write_text(json.dumps({"devices": []}))

        removed = await remove_device(devices_file, "550e8400-e29b-41d4-a716-446655440099")

        assert removed is False

    @pytest.mark.asyncio
    async def test_remove_one_of_many_devices(self, tmp_path: Path):
        """Remove one device from multiple."""
        devices_file = tmp_path / "devices.json"
        id1 = "550e8400-e29b-41d4-a716-446655440006"
        id2 = "550e8400-e29b-41d4-a716-446655440007"

        # Add two devices
        await add_or_update_device(
            devices_file=devices_file,
            installation_id=id1,
            device_name="device1",
            device_type="iphone",
            push_url="https://example.com/push/device1",
        )
        await add_or_update_device(
            devices_file=devices_file,
            installation_id=id2,
            device_name="device2",
            device_type="ipad",
            push_url="https://example.com/push/device2",
        )

        # Remove first device
        removed = await remove_device(devices_file, id1)

        assert removed is True
        data = json.loads(devices_file.read_text())
        assert len(data["devices"]) == 1
        assert data["devices"][0]["installation_id"] == id2


class TestGetDevice:
    """Test device retrieval."""

    @pytest.mark.asyncio
    async def test_get_existing_device(self, tmp_path: Path):
        """Get existing device."""
        devices_file = tmp_path / "devices.json"
        installation_id = "550e8400-e29b-41d4-a716-446655440008"

        await add_or_update_device(
            devices_file=devices_file,
            installation_id=installation_id,
            device_name="test-device",
            device_type="iphone",
            push_url="https://example.com/push/test",
        )

        device = await get_device(devices_file, installation_id)

        assert device is not None
        assert device.installation_id == installation_id
        assert device.device_name == "test-device"
        assert device.device_type == "iphone"

    @pytest.mark.asyncio
    async def test_get_nonexistent_device(self, tmp_path: Path):
        """Get nonexistent device returns None."""
        devices_file = tmp_path / "devices.json"
        devices_file.write_text(json.dumps({"devices": []}))

        device = await get_device(devices_file, "550e8400-e29b-41d4-a716-446655440099")

        assert device is None


class TestListDevices:
    """Test device listing."""

    @pytest.mark.asyncio
    async def test_list_all_devices(self, tmp_path: Path):
        """List all devices without filter."""
        devices_file = tmp_path / "devices.json"

        await add_or_update_device(
            devices_file=devices_file,
            installation_id="550e8400-e29b-41d4-a716-446655440009",
            device_name="iPhone 15",
            device_type="iphone",
            push_url="https://example.com/push/1",
        )
        await add_or_update_device(
            devices_file=devices_file,
            installation_id="550e8400-e29b-41d4-a716-446655440010",
            device_name="iPad Pro",
            device_type="ipad",
            push_url="https://example.com/push/2",
        )

        devices = await list_devices(devices_file)

        assert len(devices) == 2

    @pytest.mark.asyncio
    async def test_list_devices_filter_by_type(self, tmp_path: Path):
        """List devices filtered by device type."""
        devices_file = tmp_path / "devices.json"

        await add_or_update_device(
            devices_file=devices_file,
            installation_id="550e8400-e29b-41d4-a716-446655440011",
            device_name="iPhone 15",
            device_type="iphone",
            push_url="https://example.com/push/1",
        )
        await add_or_update_device(
            devices_file=devices_file,
            installation_id="550e8400-e29b-41d4-a716-446655440012",
            device_name="iPad Pro",
            device_type="ipad",
            push_url="https://example.com/push/2",
        )

        # Filter by iphone type
        devices = await list_devices(devices_file, device_filter="iphone")

        assert len(devices) == 1
        assert devices[0].device_type == "iphone"

    @pytest.mark.asyncio
    async def test_list_devices_filter_by_name(self, tmp_path: Path):
        """List devices filtered by device name."""
        devices_file = tmp_path / "devices.json"

        await add_or_update_device(
            devices_file=devices_file,
            installation_id="550e8400-e29b-41d4-a716-446655440013",
            device_name="Work iPhone",
            device_type="iphone",
            push_url="https://example.com/push/1",
        )
        await add_or_update_device(
            devices_file=devices_file,
            installation_id="550e8400-e29b-41d4-a716-446655440014",
            device_name="Personal iPad",
            device_type="ipad",
            push_url="https://example.com/push/2",
        )

        # Filter by name containing "Work"
        devices = await list_devices(devices_file, device_filter="Work")

        assert len(devices) == 1
        assert devices[0].device_name == "Work iPhone"

    @pytest.mark.asyncio
    async def test_list_devices_empty(self, tmp_path: Path):
        """List devices from empty registry."""
        devices_file = tmp_path / "devices.json"
        devices_file.write_text(json.dumps({"devices": []}))

        devices = await list_devices(devices_file)

        assert len(devices) == 0
