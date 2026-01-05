"""Token management service for push notifications."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Async lock for file operations (initialized in event loop)
_file_lock: asyncio.Lock | None = None


def get_file_lock() -> asyncio.Lock:
    """Get the file lock, raising if not initialized in event loop."""
    if _file_lock is None:
        msg = "File lock not initialized. Call init_file_lock() first."
        raise RuntimeError(msg)
    return _file_lock


async def init_file_lock() -> asyncio.Lock:
    """Initialize the file lock in the running event loop."""
    global _file_lock
    _file_lock = asyncio.Lock()
    return _file_lock


def validate_token_format(token: str) -> bool:
    """
    Validate APNs token format.

    Args:
        token: Device token to validate

    Returns:
        True if token is 64 hexadecimal characters, False otherwise
    """
    return bool(re.match(r"^[0-9a-fA-F]{64}$", token))


def sanitize_device_name(name: str | None) -> str | None:
    """
    Sanitize device name for safe storage and display.

    Args:
        name: Raw device name

    Returns:
        Sanitized device name or None if empty after sanitization
    """
    if not name:
        return None

    # Remove control characters and path separators
    name = re.sub(r"[\x00-\x1f\x7f/\\]", "", name)

    # Allow: alphanumeric, spaces, hyphens, apostrophes, underscores
    name = re.sub(r"[^a-zA-Z0-9\s\-'_]", "", name)

    # Collapse multiple spaces
    name = re.sub(r"\s+", " ", name)

    # Trim and limit length
    name = name.strip()[:64]

    return name if name else None


def load_tokens(tokens_file: Path) -> dict:
    """
    Load tokens from JSON file.

    Args:
        tokens_file: Path to tokens.json

    Returns:
        Parsed tokens dict with 'devices' list
    """
    if not tokens_file.exists():
        return {"devices": []}

    try:
        with tokens_file.open("r") as f:
            data = json.load(f)
            # Ensure devices key exists
            if "devices" not in data:
                data["devices"] = []
            return data
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to load tokens file: %s", e)
        # Return empty structure on error
        return {"devices": []}


def save_tokens(tokens_file: Path, tokens: dict) -> None:
    """
    Save tokens to JSON file atomically.

    Args:
        tokens_file: Path to tokens.json
        tokens: Tokens dict to save
    """
    # Ensure parent directory exists
    tokens_file.parent.mkdir(parents=True, exist_ok=True)

    # Write to temp file first
    temp_file = tokens_file.with_suffix(".json.tmp")

    try:
        with temp_file.open("w") as f:
            json.dump(tokens, f, indent=2)
            f.flush()

        # Atomic rename
        temp_file.replace(tokens_file)

        # Set secure permissions (only owner can read/write)
        tokens_file.chmod(0o600)

        logger.debug("Tokens file saved: %s", tokens_file)
    except OSError as e:
        logger.error("Failed to save tokens file: %s", e)
        # Clean up temp file if it exists
        if temp_file.exists():
            temp_file.unlink()
        raise


async def add_or_update_token(
    tokens_file: Path,
    token: str,
    device_type: Literal["iphone", "ipad", "mac"],
    device_name: str | None,
    environment: Literal["development", "production"],
) -> None:
    """
    Add new token or update existing one.

    Args:
        tokens_file: Path to tokens.json
        token: Device token (64 hex chars)
        device_type: Device type
        device_name: Optional device name
        environment: APNs environment
    """
    if not validate_token_format(token):
        msg = f"Invalid token format: {token[:8]}..."
        raise ValueError(msg)

    sanitized_name = sanitize_device_name(device_name)
    now = datetime.now(UTC).isoformat()

    async with get_file_lock():
        tokens = load_tokens(tokens_file)

        # Check if token already exists
        existing = None
        for device in tokens["devices"]:
            if device["token"] == token:
                existing = device
                break

        if existing:
            # Update existing entry
            existing["last_seen"] = now
            existing["device_name"] = sanitized_name
            existing["device_type"] = device_type
            existing["environment"] = environment
            logger.info(
                "Device updated: token=...%s, type=%s, name=%s, env=%s",
                token[-6:],
                device_type,
                sanitized_name,
                environment,
            )
        else:
            # Add new entry
            new_device = {
                "token": token,
                "device_type": device_type,
                "device_name": sanitized_name,
                "registered_at": now,
                "last_seen": now,
                "environment": environment,
            }
            tokens["devices"].append(new_device)
            logger.info(
                "Device registered: token=...%s, type=%s, name=%s, env=%s",
                token[-6:],
                device_type,
                sanitized_name,
                environment,
            )

        save_tokens(tokens_file, tokens)


async def remove_token(tokens_file: Path, token: str) -> bool:
    """
    Remove token from storage.

    Args:
        tokens_file: Path to tokens.json
        token: Device token to remove

    Returns:
        True if token was found and removed, False otherwise
    """
    async with get_file_lock():
        tokens = load_tokens(tokens_file)

        # Find and remove token
        original_count = len(tokens["devices"])
        tokens["devices"] = [d for d in tokens["devices"] if d["token"] != token]
        removed = len(tokens["devices"]) < original_count

        if removed:
            save_tokens(tokens_file, tokens)
            logger.info("Device unregistered: token=...%s", token[-6:])
        else:
            logger.warning("Token not found: token=...%s", token[-6:])

        return removed
