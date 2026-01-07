"""Tests for API call timeouts."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent import AgentService
from app.services.git import GitService
from app.services.relay_client import PrimePushRelayClient


class TestAgentServiceTimeout:
    """Tests for agent service timeouts."""

    @pytest.mark.asyncio
    async def test_agent_processing_timeout(self, tmp_path: Path) -> None:
        """Verify agent processing respects timeout."""
        agent = AgentService(
            vault_path=str(tmp_path),
            api_key="test-key",
            timeout_seconds=1,
        )

        # Mock the query function to simulate a slow operation
        async def slow_query(*args, **kwargs):
            await asyncio.sleep(2)  # Slower than timeout
            yield MagicMock()

        with patch("app.services.agent.query", side_effect=slow_query):
            result = await agent.process_dumps()

        # Should timeout and return error
        assert result["success"] is False
        assert "timed out" in result["error"].lower()
        assert "1" in result["error"]  # Should mention the timeout duration

    @pytest.mark.asyncio
    async def test_agent_processing_completes_before_timeout(self, tmp_path: Path) -> None:
        """Verify agent processing completes successfully within timeout."""
        agent = AgentService(
            vault_path=str(tmp_path),
            api_key="test-key",
            timeout_seconds=10,
        )

        # Mock the query function to simulate a fast operation
        from app.services.agent import ResultMessage

        result_message = MagicMock(spec=ResultMessage)
        result_message.is_error = False
        result_message.total_cost_usd = 0.5
        result_message.duration_ms = 100

        async def fast_query(*args, **kwargs):
            yield result_message

        with patch("app.services.agent.query", side_effect=fast_query):
            result = await agent.process_dumps()

        # Should succeed
        assert result["success"] is True
        assert result["cost_usd"] == 0.5
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_agent_timeout_configurable(self, tmp_path: Path) -> None:
        """Verify agent timeout is configurable."""
        # Test different timeout values are stored correctly
        agent1 = AgentService(
            vault_path=str(tmp_path),
            api_key="test-key",
            timeout_seconds=30,
        )
        assert agent1.timeout_seconds == 30

        agent2 = AgentService(
            vault_path=str(tmp_path),
            api_key="test-key",
            timeout_seconds=300,
        )
        assert agent2.timeout_seconds == 300


class TestRelayClientTimeout:
    """Tests for relay client timeouts."""

    @pytest.mark.asyncio
    async def test_relay_timeout_passed_to_httpx(self) -> None:
        """Verify relay client passes timeout to httpx."""
        client = PrimePushRelayClient(timeout_seconds=1)
        push_url = "https://relay.example.com/push/abc123/secret456"

        with patch("app.services.relay_client.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = AsyncMock()
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json = lambda: {"queued": False}
            mock_client.post.return_value = mock_response
            mock_client_class.return_value = mock_client

            await client.send_push(
                push_url=push_url,
                title="Test",
                body="Test",
            )

            mock_client_class.assert_called_once_with(timeout=1)

    @pytest.mark.asyncio
    async def test_relay_timeout_configurable(self) -> None:
        """Verify relay client timeout is configurable."""
        client1 = PrimePushRelayClient(timeout_seconds=3)
        assert client1.timeout == 3

        client2 = PrimePushRelayClient(timeout_seconds=10)
        assert client2.timeout == 10


class TestGitServiceTimeout:
    """Tests for Git service timeouts."""

    def test_git_timeout_configurable(self, tmp_path: Path) -> None:
        """Verify git timeout is configurable."""
        service1 = GitService(
            vault_path=str(tmp_path),
            enabled=False,
            timeout_seconds=30,
        )
        assert service1.timeout_seconds == 30

        service2 = GitService(
            vault_path=str(tmp_path),
            enabled=False,
            timeout_seconds=60,
        )
        assert service2.timeout_seconds == 60

    def test_git_disabled_no_timeout_error(self, tmp_path: Path) -> None:
        """Verify git operations are no-ops when disabled."""
        service = GitService(
            vault_path=str(tmp_path),
            enabled=False,
            timeout_seconds=1,
        )

        # These should be no-ops, not timeouts
        service.pull()  # Should not raise
        service.push()  # Should not raise

    def test_git_timeout_stored_in_init(self, tmp_path: Path) -> None:
        """Verify git timeout is stored during initialization."""
        timeout_value = 45
        service = GitService(
            vault_path=str(tmp_path),
            enabled=False,
            timeout_seconds=timeout_value,
        )

        assert service.timeout_seconds == timeout_value


class TestTimeoutConfiguration:
    """Tests for timeout configuration integration."""

    def test_config_timeout_defaults(self) -> None:
        """Verify timeout configuration has sensible defaults."""
        from app.config import Settings

        # Create minimal settings
        settings = Settings(
            anthropic_api_key="test-key",
            agent_model="claude-opus-4-5",
            auth_token="test-token",
        )

        # Verify defaults
        assert settings.anthropic_timeout_seconds == 1800  # 30 minutes
        assert settings.git_timeout_seconds == 30  # 30 seconds

    def test_config_timeout_customizable(self) -> None:
        """Verify timeout configuration is customizable."""
        from app.config import Settings

        settings = Settings(
            anthropic_api_key="test-key",
            agent_model="claude-opus-4-5",
            auth_token="test-token",
            anthropic_timeout_seconds=600,
            git_timeout_seconds=60,
        )

        assert settings.anthropic_timeout_seconds == 600
        assert settings.git_timeout_seconds == 60


class TestTimeoutErrorHandling:
    """Tests for timeout error handling."""

    @pytest.mark.asyncio
    async def test_agent_timeout_returns_error_dict(self, tmp_path: Path) -> None:
        """Verify agent timeout returns proper error structure."""
        agent = AgentService(
            vault_path=str(tmp_path),
            api_key="test-key",
            timeout_seconds=1,
        )

        async def slow_query(*args, **kwargs):
            await asyncio.sleep(2)
            yield MagicMock()

        with patch("app.services.agent.query", side_effect=slow_query):
            result = await agent.process_dumps()

        # Verify error structure
        assert "success" in result
        assert "error" in result
        assert "cost_usd" in result
        assert "duration_ms" in result
        assert result["success"] is False
        assert result["cost_usd"] is None
        assert result["duration_ms"] == 0

    @pytest.mark.asyncio
    async def test_relay_calls_raise_for_status(self) -> None:
        """Verify relay client checks HTTP status."""
        client = PrimePushRelayClient(timeout_seconds=1)
        push_url = "https://relay.example.com/push/abc123/secret456"

        with patch("app.services.relay_client.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = AsyncMock()
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json = lambda: {"queued": False}
            mock_client.post.return_value = mock_response
            mock_client_class.return_value = mock_client

            await client.send_push(
                push_url=push_url,
                title="Test",
                body="Test",
            )

            mock_response.raise_for_status.assert_called_once()
