"""Agent identity service for managing persistent agent ID."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from app.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

# Async lock for file operations (initialized in event loop)
_file_lock: asyncio.Lock | None = None


class AgentIdentity(BaseModel):
    """Agent identity information."""

    prime_agent_id: str  # Format: "agent_abc123def456"
    created_at: str  # ISO8601 timestamp
    last_loaded: str  # ISO8601 timestamp


class AgentIdentityService:
    """Service for managing persistent agent identity."""

    def __init__(self, data_path: Path) -> None:
        """Initialize service with data directory path.

        Args:
            data_path: Path to data directory (e.g., /data)
        """
        self.data_path = data_path
        self.identity_file = data_path / "agent" / "identity.json"
        self._cached_identity: AgentIdentity | None = None

    def _generate_agent_id(self) -> str:
        """Generate new short hex agent ID.

        Returns:
            Agent ID in format: agent_abc123def456 (16 hex chars)
        """
        return f"agent_{uuid4().hex[:16]}"

    def _load_from_file(self) -> AgentIdentity | None:
        """Load identity from JSON file (without lock).

        Returns:
            AgentIdentity if file exists and is valid, None otherwise
        """
        if not self.identity_file.exists():
            return None

        try:
            with self.identity_file.open("r") as f:
                data = json.load(f)
                identity = AgentIdentity(**data)
                # Update last_loaded timestamp
                identity.last_loaded = datetime.now(UTC).isoformat()
                return identity
        except (json.JSONDecodeError, OSError, ValueError) as e:
            logger.error(
                "Failed to load agent identity",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "path": str(self.identity_file),
                },
            )
            return None

    def _save_to_file(self, identity: AgentIdentity) -> None:
        """Save identity to JSON file atomically (without lock).

        Args:
            identity: AgentIdentity to save

        Raises:
            ConfigurationError: If file operations fail
        """
        # Ensure parent directory exists
        self.identity_file.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file first (atomic write pattern)
        temp_file = self.identity_file.with_suffix(".json.tmp")

        try:
            with temp_file.open("w") as f:
                json.dump(identity.model_dump(), f, indent=2)
                f.flush()

            # Atomic rename
            temp_file.replace(self.identity_file)

            # Secure permissions (owner read/write only)
            self.identity_file.chmod(0o600)

            logger.info(
                "Agent identity saved",
                extra={
                    "prime_agent_id": identity.prime_agent_id,
                    "path": str(self.identity_file),
                },
            )
        except OSError as e:
            logger.error(
                "Failed to save agent identity",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "path": str(self.identity_file),
                },
            )
            # Clean up temp file
            if temp_file.exists():
                temp_file.unlink()
            raise ConfigurationError(
                "Failed to save agent identity",
                context={
                    "operation": "save_identity",
                    "path": str(self.identity_file),
                    "error": str(e),
                },
            ) from e

    async def get_or_create_identity(self) -> AgentIdentity:
        """Get existing identity or create new one.

        Thread-safe with file locking. Uses cached value if available.

        Returns:
            AgentIdentity with prime_agent_id

        Raises:
            ConfigurationError: If file operations fail
        """
        # Return cached identity if available
        if self._cached_identity is not None:
            return self._cached_identity

        async with get_file_lock():
            # Try loading from file
            identity = self._load_from_file()

            if identity is None:
                # Generate new identity
                now = datetime.now(UTC).isoformat()
                identity = AgentIdentity(
                    prime_agent_id=self._generate_agent_id(),
                    created_at=now,
                    last_loaded=now,
                )

                # Save to disk
                self._save_to_file(identity)

                logger.info(
                    "New agent identity created",
                    extra={
                        "prime_agent_id": identity.prime_agent_id,
                        "created_at": identity.created_at,
                    },
                )
            else:
                # Update last_loaded and save
                self._save_to_file(identity)

                logger.debug(
                    "Agent identity loaded",
                    extra={
                        "prime_agent_id": identity.prime_agent_id,
                        "created_at": identity.created_at,
                    },
                )

            # Cache identity
            self._cached_identity = identity
            return identity

    def get_cached_identity(self) -> str | None:
        """Get cached prime_agent_id without file I/O.

        Returns:
            Cached prime_agent_id or None if not initialized
        """
        return self._cached_identity.prime_agent_id if self._cached_identity else None


def get_file_lock() -> asyncio.Lock:
    """Get the file lock, raising if not initialized.

    Returns:
        Initialized file lock

    Raises:
        RuntimeError: If lock not initialized in event loop
    """
    if _file_lock is None:
        msg = "File lock not initialized. Call init_file_lock() first."
        raise RuntimeError(msg)
    return _file_lock


async def init_file_lock() -> asyncio.Lock:
    """Initialize file lock in running event loop.

    Returns:
        Initialized file lock
    """
    global _file_lock
    _file_lock = asyncio.Lock()
    return _file_lock
