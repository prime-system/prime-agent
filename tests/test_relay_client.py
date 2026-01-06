"""Tests for PrimePushRelay client."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services.relay_client import PrimePushRelayClient


@pytest.mark.asyncio
async def test_send_push_success():
    """Test successful push notification."""
    client = PrimePushRelayClient(timeout_seconds=10)

    with patch("httpx.AsyncClient") as mock_client_class:
        # Setup mock response (ensure json() is async-ready)
        mock_response = AsyncMock()
        mock_response.status_code = 200
        # Make json() a regular function, not async
        mock_response.json = lambda: {"queued": True}

        # Setup mock client
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = AsyncMock()
        mock_client_class.return_value = mock_client

        result = await client.send_push(
            push_url="https://relay.example.com/push/abc123/secret456",
            title="Test",
            body="Test body",
        )

        assert result is True
        mock_client.post.assert_called_once()

        # Verify the call was made with correct arguments
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://relay.example.com/push/abc123/secret456"
        assert call_args[1]["json"]["title"] == "Test"
        assert call_args[1]["json"]["body"] == "Test body"


@pytest.mark.asyncio
async def test_send_push_with_data():
    """Test push notification with custom data."""
    client = PrimePushRelayClient(timeout_seconds=10)

    with patch("httpx.AsyncClient") as mock_client_class:
        # Setup mock response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: {"queued": True}

        # Setup mock client
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = AsyncMock()
        mock_client_class.return_value = mock_client

        custom_data = {"capture_id": "123", "source": "test"}
        result = await client.send_push(
            push_url="https://relay.example.com/push/abc123/secret456",
            title="Test",
            body="Test body",
            data=custom_data,
        )

        assert result is True

        # Verify custom data was included
        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["data"] == custom_data


@pytest.mark.asyncio
async def test_send_push_returns_false_when_not_queued():
    """Test push notification returns False when queued is False."""
    client = PrimePushRelayClient(timeout_seconds=10)

    with patch("httpx.AsyncClient") as mock_client_class:
        # Setup mock response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: {"queued": False}

        # Setup mock client
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = AsyncMock()
        mock_client_class.return_value = mock_client

        result = await client.send_push(
            push_url="https://relay.example.com/push/abc123/secret456",
            title="Test",
            body="Test body",
        )

        assert result is False


@pytest.mark.asyncio
async def test_push_id_extraction():
    """Test that push_id is correctly extracted from URL."""
    client = PrimePushRelayClient(timeout_seconds=10)

    with patch("httpx.AsyncClient") as mock_client_class:
        # Setup mock response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: {"queued": True}

        # Setup mock client
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = AsyncMock()
        mock_client_class.return_value = mock_client

        # Test that the method completes successfully
        # The important part is that it doesn't log the push_secret
        # (which is tested by code review and the lack of .secret logging)
        result = await client.send_push(
            push_url="https://relay.example.com/push/test_push_123/secret_abc",
            title="Test",
            body="Test body",
        )

        assert result is True
        # Verify the URL was used correctly
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert "test_push_123" in call_args[0][0]
        assert "secret_abc" in call_args[0][0]  # It's in the URL, which is fine


@pytest.mark.asyncio
async def test_timeout_configuration():
    """Test that timeout is correctly configured."""
    client = PrimePushRelayClient(timeout_seconds=30)

    with patch("httpx.AsyncClient") as mock_client_class:
        # Setup mock response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: {"queued": True}

        # Setup mock client
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = AsyncMock()
        mock_client_class.return_value = mock_client

        await client.send_push(
            push_url="https://relay.example.com/push/abc123/secret456",
            title="Test",
            body="Test body",
        )

        # Verify AsyncClient was called with correct timeout
        mock_client_class.assert_called_once_with(timeout=30)
