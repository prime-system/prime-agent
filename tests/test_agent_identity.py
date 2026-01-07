"""Unit tests for agent identity service."""

import asyncio
import json
import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.services.agent_identity import (
    AgentIdentity,
    AgentIdentityService,
    get_file_lock,
    init_file_lock,
)


@pytest.fixture(autouse=True)
async def setup_file_lock():
    """Initialize file lock before each async test."""
    await init_file_lock()


class TestAgentIdentity:
    """Test AgentIdentity model."""

    def test_model_validation(self):
        """Test Pydantic model validation."""
        identity = AgentIdentity(
            prime_agent_id="agent_abc123def456",
            created_at="2026-01-07T10:00:00Z",
            last_loaded="2026-01-07T10:00:00Z",
        )
        assert identity.prime_agent_id == "agent_abc123def456"
        assert identity.created_at == "2026-01-07T10:00:00Z"
        assert identity.last_loaded == "2026-01-07T10:00:00Z"


class TestAgentIdentityService:
    """Test AgentIdentityService functionality."""

    def test_service_initialization(self, tmp_path: Path):
        """Test service initializes with data path."""
        service = AgentIdentityService(tmp_path)
        assert service.data_path == tmp_path
        assert service.identity_file == tmp_path / "agent" / "identity.json"
        assert service._cached_identity is None

    def test_generate_agent_id_format(self, tmp_path: Path):
        """Test generated ID matches expected format."""
        service = AgentIdentityService(tmp_path)
        agent_id = service._generate_agent_id()

        # Check format: agent_[16 hex chars]
        assert agent_id.startswith("agent_")
        hex_part = agent_id[6:]
        assert len(hex_part) == 16
        assert all(c in "0123456789abcdef" for c in hex_part)

    def test_generate_agent_id_uniqueness(self, tmp_path: Path):
        """Test that multiple calls generate unique IDs."""
        service = AgentIdentityService(tmp_path)
        ids = {service._generate_agent_id() for _ in range(100)}
        assert len(ids) == 100  # All unique

    @pytest.mark.asyncio
    async def test_get_or_create_generates_new_identity(self, tmp_path: Path):
        """Test that get_or_create generates new identity when file doesn't exist."""
        service = AgentIdentityService(tmp_path)
        identity = await service.get_or_create_identity()

        assert identity.prime_agent_id.startswith("agent_")
        assert len(identity.prime_agent_id) == 22  # "agent_" + 16 hex chars
        assert identity.created_at
        assert identity.last_loaded

    @pytest.mark.asyncio
    async def test_identity_persists_to_disk(self, tmp_path: Path):
        """Test that identity is saved to disk."""
        service = AgentIdentityService(tmp_path)
        identity = await service.get_or_create_identity()

        # Check file exists
        assert service.identity_file.exists()

        # Check file content
        with service.identity_file.open("r") as f:
            data = json.load(f)
            assert data["prime_agent_id"] == identity.prime_agent_id
            assert data["created_at"] == identity.created_at

    @pytest.mark.asyncio
    async def test_identity_survives_service_restart(self, tmp_path: Path):
        """Test that identity persists across service restarts."""
        # First service instance
        service1 = AgentIdentityService(tmp_path)
        identity1 = await service1.get_or_create_identity()
        original_id = identity1.prime_agent_id

        # Second service instance (simulates restart)
        service2 = AgentIdentityService(tmp_path)
        identity2 = await service2.get_or_create_identity()

        # Should be the same ID
        assert identity2.prime_agent_id == original_id
        assert identity2.created_at == identity1.created_at

    @pytest.mark.asyncio
    async def test_file_has_secure_permissions(self, tmp_path: Path):
        """Test that identity file has secure permissions (0o600)."""
        service = AgentIdentityService(tmp_path)
        await service.get_or_create_identity()

        # Check file permissions
        file_stat = service.identity_file.stat()
        file_mode = stat.filemode(file_stat.st_mode)
        # Should be -rw------- (owner read/write only)
        assert file_mode == "-rw-------"

    @pytest.mark.asyncio
    async def test_atomic_write_pattern(self, tmp_path: Path):
        """Test that file writes use atomic pattern (temp file + rename)."""
        service = AgentIdentityService(tmp_path)
        await service.get_or_create_identity()

        # After successful write, temp file should be gone and final file exists
        temp_file = service.identity_file.with_suffix(".json.tmp")
        assert not temp_file.exists(), "Temp file should be removed after atomic rename"
        assert service.identity_file.exists(), "Final file should exist after atomic write"

    @pytest.mark.asyncio
    async def test_cached_identity_returns_same_id(self, tmp_path: Path):
        """Test that cached identity is returned on subsequent calls."""
        service = AgentIdentityService(tmp_path)

        # First call loads/creates
        identity1 = await service.get_or_create_identity()
        # Second call should use cache
        identity2 = await service.get_or_create_identity()

        assert identity1.prime_agent_id == identity2.prime_agent_id
        assert identity1 is identity2  # Same object reference

    def test_get_cached_identity_before_init(self, tmp_path: Path):
        """Test get_cached_identity returns None before initialization."""
        service = AgentIdentityService(tmp_path)
        assert service.get_cached_identity() is None

    @pytest.mark.asyncio
    async def test_get_cached_identity_after_init(self, tmp_path: Path):
        """Test get_cached_identity returns ID after initialization."""
        service = AgentIdentityService(tmp_path)
        identity = await service.get_or_create_identity()
        assert service.get_cached_identity() == identity.prime_agent_id


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_corrupted_json_generates_new_id(self, tmp_path: Path):
        """Test that corrupted JSON file triggers new ID generation."""
        service = AgentIdentityService(tmp_path)

        # Create identity file with corrupted JSON
        service.identity_file.parent.mkdir(parents=True, exist_ok=True)
        service.identity_file.write_text("{invalid json")

        # Should generate new identity without crashing
        identity = await service.get_or_create_identity()
        assert identity.prime_agent_id.startswith("agent_")
        assert len(identity.prime_agent_id) == 22

    @pytest.mark.asyncio
    async def test_missing_file_generates_new_id(self, tmp_path: Path):
        """Test that missing file generates new ID."""
        service = AgentIdentityService(tmp_path)

        # Ensure file doesn't exist
        assert not service.identity_file.exists()

        # Should generate new identity
        identity = await service.get_or_create_identity()
        assert identity.prime_agent_id.startswith("agent_")

    @pytest.mark.asyncio
    async def test_readonly_filesystem_raises_error(self, tmp_path: Path):
        """Test that read-only filesystem raises ConfigurationError."""
        from app.exceptions import ConfigurationError

        service = AgentIdentityService(tmp_path)

        # Make directory read-only
        service.identity_file.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(service.identity_file.parent, 0o555)

        try:
            with pytest.raises(ConfigurationError) as exc_info:
                await service.get_or_create_identity()

            assert "Failed to save agent identity" in str(exc_info.value)
        finally:
            # Restore permissions for cleanup
            os.chmod(service.identity_file.parent, 0o755)

    def test_lock_not_initialized_raises_error(self):
        """Test that get_file_lock raises RuntimeError if not initialized."""
        # Reset lock
        import app.services.agent_identity as agent_identity_module

        agent_identity_module._file_lock = None

        with pytest.raises(RuntimeError, match="File lock not initialized"):
            get_file_lock()


class TestConcurrency:
    """Test concurrency and locking behavior."""

    @pytest.mark.asyncio
    async def test_concurrent_access_returns_same_id(self, tmp_path: Path):
        """Test that concurrent calls return same ID."""
        service = AgentIdentityService(tmp_path)

        # Simulate concurrent access
        results = await asyncio.gather(
            service.get_or_create_identity(),
            service.get_or_create_identity(),
            service.get_or_create_identity(),
            service.get_or_create_identity(),
            service.get_or_create_identity(),
        )

        # All should return same ID
        ids = {r.prime_agent_id for r in results}
        assert len(ids) == 1

    @pytest.mark.asyncio
    async def test_file_lock_prevents_races(self, tmp_path: Path):
        """Test that file lock prevents race conditions."""
        service = AgentIdentityService(tmp_path)

        async def create_identity():
            return await service.get_or_create_identity()

        # Run multiple tasks concurrently
        tasks = [asyncio.create_task(create_identity()) for _ in range(10)]
        results = await asyncio.gather(*tasks)

        # All should have same ID
        ids = {r.prime_agent_id for r in results}
        assert len(ids) == 1


# Note: API integration tests are covered by full integration test suite
# The unit tests above provide comprehensive coverage of the service functionality
