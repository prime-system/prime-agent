"""Unit tests for APNService."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.apn_service import APNService


@pytest.fixture
def temp_devices_file():
    """Create a temporary devices file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        devices_file = Path(tmpdir) / "devices.json"
        yield devices_file


@pytest.fixture
def sample_devices(temp_devices_file):
    """Create sample device data."""
    devices = {
        "devices": [
            {
                "token": "a" * 64,
                "device_type": "iphone",
                "device_name": "michaels-iphone",
                "registered_at": "2025-12-30T00:00:00+00:00",
                "last_seen": "2025-12-30T00:00:00+00:00",
                "environment": "production",
            },
            {
                "token": "b" * 64,
                "device_type": "ipad",
                "device_name": "michaels-ipad",
                "registered_at": "2025-12-30T00:00:00+00:00",
                "last_seen": "2025-12-30T00:00:00+00:00",
                "environment": "development",
            },
            {
                "token": "c" * 64,
                "device_type": "mac",
                "device_name": None,
                "registered_at": "2025-12-30T00:00:00+00:00",
                "last_seen": "2025-12-30T00:00:00+00:00",
                "environment": "production",
            },
        ]
    }
    with temp_devices_file.open("w") as f:
        json.dump(devices, f)
    return temp_devices_file


@pytest.fixture
def mock_apns_client():
    """Create a mock APNs client."""
    return MagicMock()


@pytest.fixture
def mock_p8_key():
    """Mock P8 key content."""
    return """-----BEGIN PRIVATE KEY-----
MIGTAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBHkwdwIBAQQg...
-----END PRIVATE KEY-----"""


@pytest.fixture
def apn_service_instance(temp_devices_file, mock_apns_client, mock_p8_key):
    """Create an APNService instance with mocked APNs client."""
    with patch("app.services.apn_service.APNs", return_value=mock_apns_client):
        return APNService(
            devices_file=temp_devices_file,
            key_content=mock_p8_key,
            team_id="TEAM123",
            key_id="KEY123",
            bundle_id="com.example.prime",
            environment="production",
        )


class TestAPNServiceInitialization:
    """Test APNService initialization."""

    def test_init_success(self, mock_p8_key):
        """Test successful APNService initialization."""
        with patch("app.services.apn_service.APNs") as mock_apns:
            service = APNService(
                devices_file=Path("/tmp/devices.json"),
                key_content=mock_p8_key,
                team_id="TEAM123",
                key_id="KEY123",
                bundle_id="com.example.prime",
                environment="production",
            )

            assert service.bundle_id == "com.example.prime"
            assert service.environment == "production"
            mock_apns.assert_called_once()

    def test_init_with_sandbox(self, mock_p8_key):
        """Test APNService initialization with sandbox environment."""
        with patch("app.services.apn_service.APNs") as mock_apns:
            APNService(
                devices_file=Path("/tmp/devices.json"),
                key_content=mock_p8_key,
                team_id="TEAM123",
                key_id="KEY123",
                bundle_id="com.example.prime",
                environment="development",
            )

            # Check that use_sandbox=True was passed
            _args, kwargs = mock_apns.call_args
            assert kwargs.get("use_sandbox") is True

    def test_init_invalid_credentials(self, mock_p8_key):
        """Test APNService initialization with invalid credentials."""
        with patch("app.services.apn_service.APNs", side_effect=Exception("Invalid key")), \
             pytest.raises(ValueError, match="Failed to initialize APNs client"):
            APNService(
                devices_file=Path("/tmp/devices.json"),
                key_content=mock_p8_key,
                team_id="TEAM123",
                key_id="KEY123",
                bundle_id="com.example.prime",
            )

    def test_init_empty_key_content(self):
        """Test APNService initialization with empty key content."""
        with pytest.raises(ValueError, match="APNs key content is empty"):
            APNService(
                devices_file=Path("/tmp/devices.json"),
                key_content="",
                team_id="TEAM123",
                key_id="KEY123",
                bundle_id="com.example.prime",
            )


class TestAPNServiceSendToDevice:
    """Test send_to_device method."""

    @pytest.mark.asyncio
    async def test_send_to_device_success(self, apn_service_instance):
        """Test successful send to device."""
        apn_service_instance.client.send_notification = AsyncMock()

        result = await apn_service_instance.send_to_device(
            device_token="a" * 64,
            title="Test Title",
            body="Test Body",
        )

        assert result["success"] is True
        assert result["status"] == "sent"
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_send_to_device_invalid_token(self, apn_service_instance):
        """Test send to device with invalid token format."""
        result = await apn_service_instance.send_to_device(
            device_token="invalid-token",
            title="Test",
            body="Test",
        )

        assert result["success"] is False
        assert result["status"] == "invalid_token"

    @pytest.mark.asyncio
    async def test_send_to_device_bad_token_error(self, apn_service_instance):
        """Test auto-removal of device with BadDeviceToken error."""
        apn_service_instance.client.send_notification = AsyncMock(
            side_effect=Exception("BadDeviceToken")
        )

        result = await apn_service_instance.send_to_device(
            device_token="a" * 64,
            title="Test",
            body="Test",
        )

        assert result["success"] is False
        assert result["status"] == "invalid_token"

    @pytest.mark.asyncio
    async def test_send_to_device_with_priority_high(self, apn_service_instance):
        """Test send with high priority."""
        apn_service_instance.client.send_notification = AsyncMock()

        result = await apn_service_instance.send_to_device(
            device_token="a" * 64,
            title="Test",
            body="Test",
            priority="high",
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_send_to_device_with_badge(self, apn_service_instance):
        """Test send with badge count."""
        apn_service_instance.client.send_notification = AsyncMock()

        result = await apn_service_instance.send_to_device(
            device_token="a" * 64,
            title="Test",
            body="Test",
            badge=5,
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_send_to_device_with_custom_data(self, apn_service_instance):
        """Test send with custom data."""
        apn_service_instance.client.send_notification = AsyncMock()

        result = await apn_service_instance.send_to_device(
            device_token="a" * 64,
            title="Test",
            body="Test",
            data={"action": "process_dump", "id": "123"},
        )

        assert result["success"] is True


class TestAPNServiceSendToAll:
    """Test send_to_all method."""

    @pytest.mark.asyncio
    async def test_send_to_all_success(self, apn_service_instance, sample_devices):
        """Test successful send to all devices."""
        apn_service_instance.devices_file = sample_devices
        apn_service_instance.client.send_notification = AsyncMock()

        result = await apn_service_instance.send_to_all(
            title="Test",
            body="Test",
        )

        assert result["success"] is True
        assert result["sent"] == 3
        assert result["failed"] == 0
        assert len(result["devices"]) == 3

    @pytest.mark.asyncio
    async def test_send_to_all_with_filter_by_type(self, apn_service_instance, sample_devices):
        """Test send filtered by device type."""
        apn_service_instance.devices_file = sample_devices
        apn_service_instance.client.send_notification = AsyncMock()

        result = await apn_service_instance.send_to_all(
            title="Test",
            body="Test",
            device_filter="iphone",
        )

        assert result["sent"] == 1
        assert result["devices"][0]["name"] == "michaels-iphone"

    @pytest.mark.asyncio
    async def test_send_to_all_with_filter_multiple_types(self, apn_service_instance, sample_devices):
        """Test send filtered by multiple device types."""
        apn_service_instance.devices_file = sample_devices
        apn_service_instance.client.send_notification = AsyncMock()

        result = await apn_service_instance.send_to_all(
            title="Test",
            body="Test",
            device_filter="iphone,mac",
        )

        assert result["sent"] == 2

    @pytest.mark.asyncio
    async def test_send_to_all_with_environment_filter(self, apn_service_instance, sample_devices):
        """Test send filtered by environment."""
        apn_service_instance.devices_file = sample_devices
        apn_service_instance.client.send_notification = AsyncMock()

        result = await apn_service_instance.send_to_all(
            title="Test",
            body="Test",
            environment_filter="development",
        )

        assert result["sent"] == 1
        assert result["devices"][0]["name"] == "michaels-ipad"

    @pytest.mark.asyncio
    async def test_send_to_all_with_failed_devices(self, apn_service_instance, sample_devices):
        """Test send with some device failures."""
        apn_service_instance.devices_file = sample_devices

        # Mock first device success, second failure, third success
        async def mock_send(request):
            if request.device_token == "b" * 64:
                error_msg = "Unregistered"
                raise Exception(error_msg)

        apn_service_instance.client.send_notification = AsyncMock(side_effect=mock_send)

        result = await apn_service_instance.send_to_all(
            title="Test",
            body="Test",
        )

        assert result["sent"] == 2
        assert result["failed"] == 1


class TestAPNServiceListDevices:
    """Test list_devices method."""

    def test_list_all_devices(self, apn_service_instance, sample_devices):
        """Test listing all devices."""
        apn_service_instance.devices_file = sample_devices

        devices = apn_service_instance.list_devices()

        assert len(devices) == 3
        # Tokens should be truncated
        assert devices[0]["token"].startswith("...")

    def test_list_devices_filter_by_type(self, apn_service_instance, sample_devices):
        """Test listing devices filtered by type."""
        apn_service_instance.devices_file = sample_devices

        devices = apn_service_instance.list_devices(device_filter="iphone")

        assert len(devices) == 1
        assert devices[0]["device_type"] == "iphone"

    def test_list_devices_filter_by_environment(self, apn_service_instance, sample_devices):
        """Test listing devices filtered by environment."""
        apn_service_instance.devices_file = sample_devices

        devices = apn_service_instance.list_devices(environment_filter="production")

        assert len(devices) == 2
        assert all(d["environment"] == "production" for d in devices)

    def test_get_device_count(self, apn_service_instance, sample_devices):
        """Test getting device count."""
        apn_service_instance.devices_file = sample_devices

        count = apn_service_instance.get_device_count()

        assert count == 3
