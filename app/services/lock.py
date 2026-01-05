"""
Shared lock for all vault operations.

This module provides a global lock that serializes all operations that modify
the vault filesystem and git repository. Both the capture endpoint and the
agent worker use this lock to prevent race conditions and git conflicts.

IMPORTANT: The lock is created inside the running event loop via init_vault_lock(),
not at module import time. This prevents asyncio warnings and ensures the lock
belongs to the correct event loop.
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Global reference to the lock (created in lifespan via init_vault_lock())
_vault_lock: Optional[asyncio.Lock] = None


def get_vault_lock() -> asyncio.Lock:
    """
    Get the vault lock, raising error if not initialized.

    This function is safe to call from any async function. It ensures the lock
    has been properly initialized in the running event loop.

    Returns:
        asyncio.Lock instance for vault operations

    Raises:
        RuntimeError: If lock not initialized (must call init_vault_lock() in app lifespan)
    """
    if _vault_lock is None:
        raise RuntimeError(
            "Vault lock not initialized. Must call init_vault_lock() in app lifespan."
        )
    return _vault_lock


async def init_vault_lock() -> asyncio.Lock:
    """
    Initialize the vault lock in the running event loop.

    This function MUST be called once at application startup in the FastAPI
    lifespan context manager. It creates the lock within the running event loop,
    which is the correct way to initialize asyncio primitives.

    Returns:
        Initialized asyncio.Lock

    Raises:
        RuntimeError: If called when lock is already initialized
    """
    global _vault_lock
    if _vault_lock is not None:
        raise RuntimeError("Vault lock already initialized")
    _vault_lock = asyncio.Lock()
    logger.debug("Vault lock initialized in event loop")
    return _vault_lock


async def reset_lock_for_testing() -> None:
    """
    Reset lock for test teardown (testing only).

    This should only be called in test fixtures to clean up between tests.
    Never call this in production code.
    """
    global _vault_lock
    _vault_lock = None
