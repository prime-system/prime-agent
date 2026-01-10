"""Unit tests for PushNotificationService."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.services import device_registry
from app.services.push_notifications import PushNotificationService


@pytest.fixture
def temp_devices_file() -> Path:
    """Create a temporary devices file path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "devices.json"


@pytest.fixture
def mock_relay_client() -> AsyncMock:
    """Mock PrimePushRelayClient."""
    mock = AsyncMock()
    mock.send_push = AsyncMock(return_value=True)
    return mock


@pytest.mark.asyncio
async def test_send_notification_success(
    temp_devices_file: Path,
    mock_relay_client: AsyncMock,
) -> None:
    """Send notification successfully via relay client."""
    await device_registry.init_file_lock()
    await device_registry.add_or_update_device(
        devices_file=temp_devices_file,
        installation_id="install-123",
        device_name="phone",
        device_type="iphone",
        push_url="https://relay.example.com/push/abc123/secret456",
    )

    service = PushNotificationService(
        devices_file=temp_devices_file,
        relay_client=mock_relay_client,
    )

    summary = await service.send_notification(
        title="Test Notification",
        body="Body",
        data={"key": "value"},
    )

    assert summary.sent == 1
    assert summary.failed == 0
    assert summary.invalid_tokens_removed == 0
    assert len(summary.device_results) == 1
    assert summary.device_results[0].status == "sent"

    mock_relay_client.send_push.assert_awaited_once_with(
        push_url="https://relay.example.com/push/abc123/secret456",
        title="Test Notification",
        body="Body",
        data={"key": "value"},
    )


@pytest.mark.asyncio
async def test_send_notification_handles_gone(
    temp_devices_file: Path,
    mock_relay_client: AsyncMock,
) -> None:
    """410 Gone responses should remove devices."""
    await device_registry.init_file_lock()
    await device_registry.add_or_update_device(
        devices_file=temp_devices_file,
        installation_id="install-123",
        device_name="phone",
        device_type="iphone",
        push_url="https://relay.example.com/push/abc123/secret456",
    )

    mock_response = MagicMock()
    mock_response.status_code = 410
    mock_relay_client.send_push.side_effect = httpx.HTTPStatusError(
        "Gone",
        request=MagicMock(),
        response=mock_response,
    )

    service = PushNotificationService(
        devices_file=temp_devices_file,
        relay_client=mock_relay_client,
    )

    summary = await service.send_notification(
        title="Test Notification",
        body="Body",
    )

    assert summary.sent == 0
    assert summary.failed == 0
    assert summary.invalid_tokens_removed == 1
    assert summary.device_results[0].status == "invalid_binding"

    remaining_devices = await device_registry.list_devices(temp_devices_file)
    assert remaining_devices == []


@pytest.mark.asyncio
async def test_send_notification_no_devices(
    temp_devices_file: Path,
    mock_relay_client: AsyncMock,
) -> None:
    """No devices should short-circuit without relay calls."""
    await device_registry.init_file_lock()
    service = PushNotificationService(
        devices_file=temp_devices_file,
        relay_client=mock_relay_client,
    )

    summary = await service.send_notification(
        title="Test Notification",
        body="Body",
    )

    assert summary.sent == 0
    assert summary.failed == 0
    assert summary.invalid_tokens_removed == 0
    assert summary.device_results == []
    mock_relay_client.send_push.assert_not_called()
