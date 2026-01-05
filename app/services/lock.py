"""
Shared lock for all vault operations.

This module provides a global lock that serializes all operations that modify
the vault filesystem and git repository. Both the capture endpoint and the
agent worker use this lock to prevent race conditions and git conflicts.
"""

import asyncio

# Global lock shared by capture endpoint and agent worker
vault_lock = asyncio.Lock()
