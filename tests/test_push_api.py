"""Integration tests for push notifications API."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def temp_devices_file():
    """Create a temporary devices file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        devices_file = Path(tmpdir) / "devices.json"
        yield devices_file


@pytest.fixture
def mock_relay_client():
    """Mock PrimePushRelayClient."""
    mock = AsyncMock()
    mock.send_push = AsyncMock(return_value=True)
    return mock


@pytest.fixture
async def push_app(temp_devices_file, mock_relay_client, monkeypatch):
    """Create a test FastAPI app with push router."""
    from app.api import push
    from app.config import settings
    from app.dependencies import get_push_notification_service
    from app.services import device_registry
    from app.services.push_notifications import PushNotificationService

    # Initialize async file lock
    await device_registry.init_file_lock()

    # Monkey-patch settings to use temp file
    monkeypatch.setattr(
        settings._config_manager._current_settings, "apn_devices_file", temp_devices_file
    )

    app = FastAPI(title="Prime Server Test")
    app.include_router(push.router)

    # Override push notification service dependency
    push_notification_service = PushNotificationService(
        devices_file=temp_devices_file,
        relay_client=mock_relay_client,
    )
    app.dependency_overrides[get_push_notification_service] = lambda: push_notification_service

    return app


@pytest.fixture
def push_client(push_app):
    """Test client for push API."""
    with TestClient(push_app) as client:
        yield client


@pytest.fixture
def valid_register_request():
    """Valid registration request payload."""
    return {
        "installation_id": "test-uuid-12345",
        "device_type": "iphone",
        "device_name": "test-device",
        "push_url": "https://relay.example.com/push/abc123/secret456",
    }


@pytest.fixture
def auth_headers():
    """Valid authorization headers."""
    return {"Authorization": "Bearer test-token-123"}


class TestRegisterEndpoint:
    """Test POST /api/v1/devices/register endpoint."""

    def test_register_new_device(
        self, push_client, valid_register_request, auth_headers, temp_devices_file
    ):
        """Register new device successfully."""
        response = push_client.post(
            "/api/v1/devices/register",
            json=valid_register_request,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "registered successfully" in data["message"]

        # Verify file was created
        assert temp_devices_file.exists()

        # Verify content
        devices = json.loads(temp_devices_file.read_text())
        assert len(devices["devices"]) == 1
        assert devices["devices"][0]["installation_id"] == valid_register_request["installation_id"]
        assert devices["devices"][0]["device_type"] == "iphone"
        assert devices["devices"][0]["device_name"] == "test-device"
        assert devices["devices"][0]["push_url"] == valid_register_request["push_url"]

    def test_register_without_device_name(
        self, push_client, valid_register_request, auth_headers, temp_devices_file
    ):
        """Register device without device_name."""
        request = valid_register_request.copy()
        request["device_name"] = None

        response = push_client.post(
            "/api/v1/devices/register",
            json=request,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Verify device_name is None
        devices = json.loads(temp_devices_file.read_text())
        assert devices["devices"][0]["device_name"] is None

    def test_register_updates_existing_device(
        self, push_client, valid_register_request, auth_headers, temp_devices_file
    ):
        """Register same installation_id twice updates existing entry."""
        # First registration
        push_client.post(
            "/api/v1/devices/register",
            json=valid_register_request,
            headers=auth_headers,
        )

        # Second registration with same installation_id but different name
        updated_request = valid_register_request.copy()
        updated_request["device_name"] = "updated-device"
        updated_request["push_url"] = "https://relay.example.com/push/new123/newsecret"

        response = push_client.post(
            "/api/v1/devices/register",
            json=updated_request,
            headers=auth_headers,
        )

        assert response.status_code == 200

        # Verify only one device exists with updated values
        devices = json.loads(temp_devices_file.read_text())
        assert len(devices["devices"]) == 1
        assert devices["devices"][0]["device_name"] == "updated-device"
        assert devices["devices"][0]["push_url"] == updated_request["push_url"]

    def test_register_invalid_device_type(self, push_client, valid_register_request, auth_headers):
        """Register with invalid device_type returns 422."""
        request = valid_register_request.copy()
        request["device_type"] = "invalid"

        response = push_client.post(
            "/api/v1/devices/register",
            json=request,
            headers=auth_headers,
        )

        assert response.status_code == 422  # Pydantic validation error

    def test_register_missing_required_fields(self, push_client, auth_headers):
        """Register with missing required fields returns 422."""
        response = push_client.post(
            "/api/v1/devices/register",
            json={"installation_id": "test-uuid"},  # Missing push_url
            headers=auth_headers,
        )

        assert response.status_code == 422

    def test_register_without_auth(self, push_client, valid_register_request):
        """Register without auth token returns 401."""
        response = push_client.post(
            "/api/v1/devices/register",
            json=valid_register_request,
        )

        assert response.status_code == 401

    def test_register_with_invalid_auth(self, push_client, valid_register_request):
        """Register with invalid auth token returns 401."""
        response = push_client.post(
            "/api/v1/devices/register",
            json=valid_register_request,
            headers={"Authorization": "Bearer wrong-token"},
        )

        assert response.status_code == 401

    def test_register_multiple_devices(
        self, push_client, valid_register_request, auth_headers, temp_devices_file
    ):
        """Register multiple different devices."""
        # Register first device
        response1 = push_client.post(
            "/api/v1/devices/register",
            json=valid_register_request,
            headers=auth_headers,
        )
        assert response1.status_code == 200

        # Register second device with different installation_id
        request2 = valid_register_request.copy()
        request2["installation_id"] = "test-uuid-67890"
        request2["device_type"] = "ipad"
        request2["device_name"] = "device2"
        request2["push_url"] = "https://relay.example.com/push/def456/secret789"

        response2 = push_client.post(
            "/api/v1/devices/register",
            json=request2,
            headers=auth_headers,
        )
        assert response2.status_code == 200

        # Verify both devices exist
        devices = json.loads(temp_devices_file.read_text())
        assert len(devices["devices"]) == 2

    def test_register_sanitizes_device_name(
        self, push_client, valid_register_request, auth_headers, temp_devices_file
    ):
        """Register with special characters in device_name sanitizes them."""
        request = valid_register_request.copy()
        request["device_name"] = "../../etc/passwd"

        response = push_client.post(
            "/api/v1/devices/register",
            json=request,
            headers=auth_headers,
        )

        assert response.status_code == 200

        # Verify device_name was sanitized
        devices = json.loads(temp_devices_file.read_text())
        assert devices["devices"][0]["device_name"] == "etcpasswd"


class TestSendNotificationEndpoint:
    """Test POST /api/v1/notifications/send endpoint."""

    def test_send_to_single_device(
        self,
        push_client,
        valid_register_request,
        auth_headers,
        temp_devices_file,
        mock_relay_client,
    ):
        """Send notification to single registered device."""
        # Register a device first
        push_client.post(
            "/api/v1/devices/register",
            json=valid_register_request,
            headers=auth_headers,
        )

        # Send notification
        notification = {
            "title": "Test Notification",
            "body": "This is a test",
            "data": {"key": "value"},
        }

        response = push_client.post(
            "/api/v1/notifications/send",
            json=notification,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["sent"] == 1
        assert data["failed"] == 0
        assert data["invalid_tokens_removed"] == 0
        assert len(data["devices"]) == 1
        assert data["devices"][0]["status"] == "sent"

        # Verify relay client was called
        mock_relay_client.send_push.assert_called_once_with(
            push_url=valid_register_request["push_url"],
            title="Test Notification",
            body="This is a test",
            data={"key": "value"},
        )

    def test_send_to_multiple_devices(
        self,
        push_client,
        valid_register_request,
        auth_headers,
        temp_devices_file,
        mock_relay_client,
    ):
        """Send notification to multiple devices."""
        # Register two devices
        push_client.post(
            "/api/v1/devices/register",
            json=valid_register_request,
            headers=auth_headers,
        )

        request2 = valid_register_request.copy()
        request2["installation_id"] = "test-uuid-67890"
        request2["device_type"] = "ipad"
        request2["push_url"] = "https://relay.example.com/push/def456/secret789"
        push_client.post(
            "/api/v1/devices/register",
            json=request2,
            headers=auth_headers,
        )

        # Send notification
        notification = {
            "title": "Test Notification",
            "body": "This is a test",
        }

        response = push_client.post(
            "/api/v1/notifications/send",
            json=notification,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["sent"] == 2
        assert data["failed"] == 0

        # Verify relay client was called twice
        assert mock_relay_client.send_push.call_count == 2

    def test_send_with_device_filter(
        self,
        push_client,
        valid_register_request,
        auth_headers,
        temp_devices_file,
        mock_relay_client,
    ):
        """Send notification with device filter."""
        # Register two devices
        push_client.post(
            "/api/v1/devices/register",
            json=valid_register_request,
            headers=auth_headers,
        )

        request2 = valid_register_request.copy()
        request2["installation_id"] = "test-uuid-67890"
        request2["device_type"] = "ipad"
        request2["push_url"] = "https://relay.example.com/push/def456/secret789"
        push_client.post(
            "/api/v1/devices/register",
            json=request2,
            headers=auth_headers,
        )

        # Send notification with filter for iphone only
        notification = {
            "title": "Test Notification",
            "body": "This is a test",
            "device_filter": "iphone",
        }

        response = push_client.post(
            "/api/v1/notifications/send",
            json=notification,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["sent"] == 1  # Only iPhone device

        # Verify relay client was called once
        assert mock_relay_client.send_push.call_count == 1

    def test_send_handles_410_gone(
        self,
        push_client,
        valid_register_request,
        auth_headers,
        temp_devices_file,
        mock_relay_client,
    ):
        """Send notification handles 410 Gone response by removing device."""
        # Register a device
        push_client.post(
            "/api/v1/devices/register",
            json=valid_register_request,
            headers=auth_headers,
        )

        # Mock 410 Gone response
        mock_response = MagicMock()
        mock_response.status_code = 410
        mock_relay_client.send_push.side_effect = httpx.HTTPStatusError(
            "Gone", request=MagicMock(), response=mock_response
        )

        # Send notification
        notification = {
            "title": "Test Notification",
            "body": "This is a test",
        }

        response = push_client.post(
            "/api/v1/notifications/send",
            json=notification,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Success is True when there are no failed sends (invalid bindings don't count as failures)
        assert data["success"] is True
        assert data["sent"] == 0
        assert data["failed"] == 0
        assert data["invalid_tokens_removed"] == 1
        assert data["devices"][0]["status"] == "invalid_binding"

        # Verify device was removed from file
        devices = json.loads(temp_devices_file.read_text())
        assert len(devices["devices"]) == 0

    def test_send_handles_other_http_errors(
        self,
        push_client,
        valid_register_request,
        auth_headers,
        temp_devices_file,
        mock_relay_client,
    ):
        """Send notification handles non-410 HTTP errors without removing device."""
        # Register a device
        push_client.post(
            "/api/v1/devices/register",
            json=valid_register_request,
            headers=auth_headers,
        )

        # Mock 500 error
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_relay_client.send_push.side_effect = httpx.HTTPStatusError(
            "Internal Server Error", request=MagicMock(), response=mock_response
        )

        # Send notification
        notification = {
            "title": "Test Notification",
            "body": "This is a test",
        }

        response = push_client.post(
            "/api/v1/notifications/send",
            json=notification,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["sent"] == 0
        assert data["failed"] == 1
        assert data["invalid_tokens_removed"] == 0
        assert data["devices"][0]["status"] == "failed"

        # Verify device was NOT removed
        devices = json.loads(temp_devices_file.read_text())
        assert len(devices["devices"]) == 1

    def test_send_without_auth(self, push_client):
        """Send notification without auth returns 401."""
        notification = {
            "title": "Test Notification",
            "body": "This is a test",
        }

        response = push_client.post(
            "/api/v1/notifications/send",
            json=notification,
        )

        assert response.status_code == 401

    def test_send_with_invalid_auth(self, push_client):
        """Send notification with invalid auth returns 401."""
        notification = {
            "title": "Test Notification",
            "body": "This is a test",
        }

        response = push_client.post(
            "/api/v1/notifications/send",
            json=notification,
            headers={"Authorization": "Bearer wrong-token"},
        )

        assert response.status_code == 401

    def test_send_missing_required_fields(self, push_client, auth_headers):
        """Send notification with missing required fields returns 422."""
        response = push_client.post(
            "/api/v1/notifications/send",
            json={"title": "Test"},  # Missing body
            headers=auth_headers,
        )

        assert response.status_code == 422


class TestListDevicesEndpoint:
    """Test GET /api/v1/devices endpoint."""

    def test_list_devices(
        self, push_client, valid_register_request, auth_headers, temp_devices_file
    ):
        """List registered devices."""
        # Register two devices
        push_client.post(
            "/api/v1/devices/register",
            json=valid_register_request,
            headers=auth_headers,
        )

        request2 = valid_register_request.copy()
        request2["installation_id"] = "test-uuid-67890"
        request2["device_type"] = "ipad"
        request2["push_url"] = "https://relay.example.com/push/def456/secret789"
        push_client.post(
            "/api/v1/devices/register",
            json=request2,
            headers=auth_headers,
        )

        # List devices
        response = push_client.get(
            "/api/v1/devices",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["devices"]) == 2

        # Verify push_url is NOT included (security)
        for device in data["devices"]:
            assert "push_url" not in device
            assert "installation_id" in device
            assert "device_type" in device

    def test_list_devices_with_filter(
        self, push_client, valid_register_request, auth_headers, temp_devices_file
    ):
        """List devices with filter."""
        # Register two devices
        push_client.post(
            "/api/v1/devices/register",
            json=valid_register_request,
            headers=auth_headers,
        )

        request2 = valid_register_request.copy()
        request2["installation_id"] = "test-uuid-67890"
        request2["device_type"] = "ipad"
        request2["push_url"] = "https://relay.example.com/push/def456/secret789"
        push_client.post(
            "/api/v1/devices/register",
            json=request2,
            headers=auth_headers,
        )

        # List with filter
        response = push_client.get(
            "/api/v1/devices?device_filter=iphone",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["devices"][0]["device_type"] == "iphone"

    def test_list_devices_empty(self, push_client, auth_headers):
        """List devices when none registered."""
        response = push_client.get(
            "/api/v1/devices",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert len(data["devices"]) == 0

    def test_list_devices_without_auth(self, push_client):
        """List devices without auth returns 401."""
        response = push_client.get("/api/v1/devices")
        assert response.status_code == 401

    def test_list_devices_with_invalid_auth(self, push_client):
        """List devices with invalid auth returns 401."""
        response = push_client.get(
            "/api/v1/devices",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert response.status_code == 401


class TestOldEndpointsRemoved:
    """Test that old endpoints no longer exist."""

    def test_old_register_endpoint_removed(self, push_client, auth_headers):
        """Old POST /push/register endpoint should return 404."""
        response = push_client.post(
            "/api/v1/push/register",
            json={
                "token": "a" * 64,
                "device_type": "iphone",
                "environment": "production",
            },
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_old_unregister_endpoint_removed(self, push_client, auth_headers):
        """Old DELETE /push/unregister endpoint should return 404."""
        response = push_client.request(
            "DELETE",
            "/api/v1/push/unregister",
            json={"token": "a" * 64},
            headers=auth_headers,
        )
        assert response.status_code == 404
