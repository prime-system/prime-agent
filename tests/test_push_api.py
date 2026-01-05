"""Integration tests for push notifications API."""

import json
import tempfile
from pathlib import Path

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
def push_app(temp_devices_file):
    """Create a test FastAPI app with push router."""
    from app.api import push
    from app.config import settings

    # Monkey-patch settings to use temp file
    original_devices_file = settings.apn_devices_file
    settings.apn_devices_file = temp_devices_file

    # Inject None (no APNs service) for register/unregister tests
    push.init_services(None)

    app = FastAPI(title="Prime Server Test")
    app.include_router(push.router, prefix="/api/v1", tags=["push"])

    yield app

    # Restore original settings
    settings.apn_devices_file = original_devices_file


@pytest.fixture
def push_client(push_app):
    """Test client for push API."""
    with TestClient(push_app) as client:
        yield client


@pytest.fixture
def valid_register_request():
    """Valid registration request payload."""
    return {
        "token": "a" * 64,
        "device_type": "iphone",
        "device_name": "test-device",
        "environment": "production",
    }


@pytest.fixture
def auth_headers():
    """Valid authorization headers."""
    return {"Authorization": "Bearer test-token-123"}


class TestRegisterEndpoint:
    """Test POST /api/v1/push/register endpoint."""

    def test_register_new_device(
        self, push_client, valid_register_request, auth_headers, temp_devices_file
    ):
        """Register new device successfully."""
        response = push_client.post(
            "/api/v1/push/register",
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
        tokens = json.loads(temp_devices_file.read_text())
        assert len(tokens["devices"]) == 1
        assert tokens["devices"][0]["token"] == valid_register_request["token"]
        assert tokens["devices"][0]["device_type"] == "iphone"
        assert tokens["devices"][0]["device_name"] == "test-device"
        assert tokens["devices"][0]["environment"] == "production"

    def test_register_without_device_name(
        self, push_client, valid_register_request, auth_headers, temp_devices_file
    ):
        """Register device without device_name."""
        request = valid_register_request.copy()
        request["device_name"] = None

        response = push_client.post(
            "/api/v1/push/register",
            json=request,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Verify device_name is None
        tokens = json.loads(temp_devices_file.read_text())
        assert tokens["devices"][0]["device_name"] is None

    def test_register_updates_existing_token(
        self, push_client, valid_register_request, auth_headers, temp_devices_file
    ):
        """Register same token twice updates existing entry."""
        # First registration
        push_client.post(
            "/api/v1/push/register",
            json=valid_register_request,
            headers=auth_headers,
        )

        # Second registration with same token but different name
        updated_request = valid_register_request.copy()
        updated_request["device_name"] = "updated-device"

        response = push_client.post(
            "/api/v1/push/register",
            json=updated_request,
            headers=auth_headers,
        )

        assert response.status_code == 200

        # Verify only one device exists with updated name
        tokens = json.loads(temp_devices_file.read_text())
        assert len(tokens["devices"]) == 1
        assert tokens["devices"][0]["device_name"] == "updated-device"

    def test_register_invalid_token_format(self, push_client, valid_register_request, auth_headers):
        """Register with invalid token format returns 400."""
        request = valid_register_request.copy()
        request["token"] = "invalid-token"

        response = push_client.post(
            "/api/v1/push/register",
            json=request,
            headers=auth_headers,
        )

        assert response.status_code == 400
        data = response.json()
        assert "Invalid token format" in data["detail"]

    def test_register_invalid_device_type(self, push_client, valid_register_request, auth_headers):
        """Register with invalid device_type returns 422."""
        request = valid_register_request.copy()
        request["device_type"] = "invalid"

        response = push_client.post(
            "/api/v1/push/register",
            json=request,
            headers=auth_headers,
        )

        assert response.status_code == 422  # Pydantic validation error

    def test_register_invalid_environment(self, push_client, valid_register_request, auth_headers):
        """Register with invalid environment returns 422."""
        request = valid_register_request.copy()
        request["environment"] = "invalid"

        response = push_client.post(
            "/api/v1/push/register",
            json=request,
            headers=auth_headers,
        )

        assert response.status_code == 422  # Pydantic validation error

    def test_register_missing_required_fields(self, push_client, auth_headers):
        """Register with missing required fields returns 422."""
        response = push_client.post(
            "/api/v1/push/register",
            json={"token": "a" * 64},  # Missing device_type and environment
            headers=auth_headers,
        )

        assert response.status_code == 422

    def test_register_without_auth(self, push_client, valid_register_request):
        """Register without auth token returns 401."""
        response = push_client.post(
            "/api/v1/push/register",
            json=valid_register_request,
        )

        assert response.status_code == 401

    def test_register_with_invalid_auth(self, push_client, valid_register_request):
        """Register with invalid auth token returns 401."""
        response = push_client.post(
            "/api/v1/push/register",
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
            "/api/v1/push/register",
            json=valid_register_request,
            headers=auth_headers,
        )
        assert response1.status_code == 200

        # Register second device with different token
        request2 = valid_register_request.copy()
        request2["token"] = "b" * 64
        request2["device_type"] = "ipad"
        request2["device_name"] = "device2"

        response2 = push_client.post(
            "/api/v1/push/register",
            json=request2,
            headers=auth_headers,
        )
        assert response2.status_code == 200

        # Verify both devices exist
        tokens = json.loads(temp_devices_file.read_text())
        assert len(tokens["devices"]) == 2

    def test_register_sanitizes_device_name(
        self, push_client, valid_register_request, auth_headers, temp_devices_file
    ):
        """Register with special characters in device_name sanitizes them."""
        request = valid_register_request.copy()
        request["device_name"] = "../../etc/passwd"

        response = push_client.post(
            "/api/v1/push/register",
            json=request,
            headers=auth_headers,
        )

        assert response.status_code == 200

        # Verify device_name was sanitized
        tokens = json.loads(temp_devices_file.read_text())
        assert tokens["devices"][0]["device_name"] == "etcpasswd"


class TestUnregisterEndpoint:
    """Test DELETE /api/v1/push/unregister endpoint."""

    def test_unregister_existing_device(
        self, push_client, valid_register_request, auth_headers, temp_devices_file
    ):
        """Unregister existing device successfully."""
        # First register a device
        push_client.post(
            "/api/v1/push/register",
            json=valid_register_request,
            headers=auth_headers,
        )

        # Then unregister it
        response = push_client.request(
            "DELETE",
            "/api/v1/push/unregister",
            json={"token": valid_register_request["token"]},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "unregistered successfully" in data["message"]

        # Verify device was removed
        tokens = json.loads(temp_devices_file.read_text())
        assert len(tokens["devices"]) == 0

    def test_unregister_nonexistent_device(self, push_client, auth_headers):
        """Unregister nonexistent device returns success=false."""
        response = push_client.request(
            "DELETE",
            "/api/v1/push/unregister",
            json={"token": "z" * 64},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "not found" in data["message"]

    def test_unregister_one_of_multiple_devices(
        self, push_client, valid_register_request, auth_headers, temp_devices_file
    ):
        """Unregister one device when multiple exist."""
        # Register two devices
        push_client.post(
            "/api/v1/push/register",
            json=valid_register_request,
            headers=auth_headers,
        )

        request2 = valid_register_request.copy()
        request2["token"] = "b" * 64
        push_client.post(
            "/api/v1/push/register",
            json=request2,
            headers=auth_headers,
        )

        # Unregister first device
        response = push_client.request(
            "DELETE",
            "/api/v1/push/unregister",
            json={"token": valid_register_request["token"]},
            headers=auth_headers,
        )

        assert response.status_code == 200

        # Verify only second device remains
        tokens = json.loads(temp_devices_file.read_text())
        assert len(tokens["devices"]) == 1
        assert tokens["devices"][0]["token"] == "b" * 64

    def test_unregister_without_auth(self, push_client):
        """Unregister without auth token returns 401."""
        response = push_client.request(
            "DELETE",
            "/api/v1/push/unregister",
            json={"token": "a" * 64},
        )

        assert response.status_code == 401

    def test_unregister_with_invalid_auth(self, push_client):
        """Unregister with invalid auth token returns 401."""
        response = push_client.request(
            "DELETE",
            "/api/v1/push/unregister",
            json={"token": "a" * 64},
            headers={"Authorization": "Bearer wrong-token"},
        )

        assert response.status_code == 401

    def test_unregister_missing_token(self, push_client, auth_headers):
        """Unregister without token returns 422."""
        response = push_client.request(
            "DELETE",
            "/api/v1/push/unregister",
            json={},
            headers=auth_headers,
        )

        assert response.status_code == 422
