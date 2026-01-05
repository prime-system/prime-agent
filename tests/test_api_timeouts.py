"""Tests for API call timeouts."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.agent import AgentService
from app.services.apn_service import APNService
from app.services.git import GitService


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


class TestAPNServiceTimeout:
    """Tests for APNs service timeouts."""

    @pytest.mark.asyncio
    async def test_apns_send_timeout(self, tmp_path: Path) -> None:
        """Verify APNs send respects timeout."""
        devices_file = tmp_path / "devices.json"
        devices_file.write_text('{"devices": []}')

        service = APNService(
            devices_file=devices_file,
            key_content="test-key-content",
            team_id="test-team",
            key_id="test-key-id",
            bundle_id="com.test.app",
            timeout_seconds=1,
        )

        # Valid APNs device token format (hex string, 64 chars)
        valid_token = "a" * 64

        # Mock the send_notification to simulate a slow operation
        async def slow_send(*args, **kwargs):
            await asyncio.sleep(2)  # Slower than timeout

        with patch.object(service.client, "send_notification", side_effect=slow_send):
            result = await service.send_to_device(
                device_token=valid_token,
                title="Test",
                body="Test",
            )

        # Should fail due to timeout
        assert result["success"] is False
        assert "timed out" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_apns_send_completes_before_timeout(self, tmp_path: Path) -> None:
        """Verify APNs send completes successfully within timeout."""
        devices_file = tmp_path / "devices.json"
        devices_file.write_text('{"devices": []}')

        service = APNService(
            devices_file=devices_file,
            key_content="test-key-content",
            team_id="test-team",
            key_id="test-key-id",
            bundle_id="com.test.app",
            timeout_seconds=5,
        )

        # Valid APNs device token format (hex string, 64 chars)
        valid_token = "a" * 64

        # Mock the send_notification to return immediately
        async def fast_send(*args, **kwargs):
            await asyncio.sleep(0.1)  # Fast operation

        with patch.object(service.client, "send_notification", side_effect=fast_send):
            result = await service.send_to_device(
                device_token=valid_token,
                title="Test",
                body="Test",
            )

        # Should succeed
        assert result["success"] is True
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_apns_timeout_configurable(self, tmp_path: Path) -> None:
        """Verify APNs timeout is configurable."""
        devices_file = tmp_path / "devices.json"
        devices_file.write_text('{"devices": []}')

        service1 = APNService(
            devices_file=devices_file,
            key_content="test-key-content",
            team_id="test-team",
            key_id="test-key-id",
            bundle_id="com.test.app",
            timeout_seconds=3,
        )
        assert service1.timeout_seconds == 3

        service2 = APNService(
            devices_file=devices_file,
            key_content="test-key-content",
            team_id="test-team",
            key_id="test-key-id",
            bundle_id="com.test.app",
            timeout_seconds=10,
        )
        assert service2.timeout_seconds == 10


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
        assert settings.apns_timeout_seconds == 5  # 5 seconds
        assert settings.git_timeout_seconds == 30  # 30 seconds

    def test_config_timeout_customizable(self) -> None:
        """Verify timeout configuration is customizable."""
        from app.config import Settings

        settings = Settings(
            anthropic_api_key="test-key",
            agent_model="claude-opus-4-5",
            auth_token="test-token",
            anthropic_timeout_seconds=600,
            apns_timeout_seconds=10,
            git_timeout_seconds=60,
        )

        assert settings.anthropic_timeout_seconds == 600
        assert settings.apns_timeout_seconds == 10
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
    async def test_apns_timeout_returns_error_dict(self, tmp_path: Path) -> None:
        """Verify APNs timeout returns proper error structure."""
        devices_file = tmp_path / "devices.json"
        devices_file.write_text('{"devices": []}')

        service = APNService(
            devices_file=devices_file,
            key_content="test-key-content",
            team_id="test-team",
            key_id="test-key-id",
            bundle_id="com.test.app",
            timeout_seconds=1,
        )

        # Valid APNs device token format
        valid_token = "a" * 64

        async def slow_send(*args, **kwargs):
            await asyncio.sleep(2)

        with patch.object(service.client, "send_notification", side_effect=slow_send):
            result = await service.send_to_device(
                device_token=valid_token,
                title="Test",
                body="Test",
            )

        # Verify error structure
        assert "success" in result
        assert "error" in result
        assert "status" in result
        assert result["success"] is False
        assert result["error"] is not None
