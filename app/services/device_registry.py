"""Device registry service for managing push notification endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Async lock for file operations (initialized in event loop)
_file_lock: asyncio.Lock | None = None


class Device(BaseModel):
    """Device registration entry."""

    installation_id: str  # UUID from app (primary key)
    device_name: str | None
    device_type: Literal["iphone", "ipad", "mac"]
    push_url: str  # Capability URL from PrimePushRelay
    registered_at: str  # ISO8601 timestamp
    last_seen: str  # ISO8601 timestamp


class DeviceRegistry(BaseModel):
    """Device registry structure."""

    devices: list[Device] = []


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


def load_devices(devices_file: Path) -> DeviceRegistry:
    """
    Load devices from JSON file.

    Args:
        devices_file: Path to devices.json

    Returns:
        DeviceRegistry with list of devices
    """
    if not devices_file.exists():
        return DeviceRegistry()

    try:
        with devices_file.open("r") as f:
            data = json.load(f)
            return DeviceRegistry(**data)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to load devices file: %s", e)
        # Return empty structure on error
        return DeviceRegistry()


def save_devices(devices_file: Path, registry: DeviceRegistry) -> None:
    """
    Save devices to JSON file atomically.

    Args:
        devices_file: Path to devices.json
        registry: DeviceRegistry to save
    """
    # Ensure parent directory exists
    devices_file.parent.mkdir(parents=True, exist_ok=True)

    # Write to temp file first
    temp_file = devices_file.with_suffix(".json.tmp")

    try:
        with temp_file.open("w") as f:
            json.dump(registry.model_dump(), f, indent=2)
            f.flush()

        # Atomic rename
        temp_file.replace(devices_file)

        # Set secure permissions (only owner can read/write)
        devices_file.chmod(0o600)

        logger.debug("Devices file saved: %s", devices_file)
    except OSError as e:
        logger.error("Failed to save devices file: %s", e)
        # Clean up temp file if it exists
        if temp_file.exists():
            temp_file.unlink()
        raise


async def add_or_update_device(
    devices_file: Path,
    installation_id: str,
    device_name: str | None,
    device_type: Literal["iphone", "ipad", "mac"],
    push_url: str,
) -> None:
    """
    Add new device or update existing one.

    Matches on installation_id as primary key.
    Updates last_seen timestamp on every call.

    Args:
        devices_file: Path to devices.json
        installation_id: UUID from app (primary key)
        device_name: Optional device name
        device_type: Device type
        push_url: Capability URL from PrimePushRelay
    """
    sanitized_name = sanitize_device_name(device_name)
    now = datetime.now(UTC).isoformat()

    async with get_file_lock():
        registry = load_devices(devices_file)

        # Check if device already exists
        existing = None
        for device in registry.devices:
            if device.installation_id == installation_id:
                existing = device
                break

        if existing:
            # Update existing entry
            existing.last_seen = now
            existing.device_name = sanitized_name
            existing.device_type = device_type
            existing.push_url = push_url
            logger.info(
                "Device updated: id=%s, type=%s, name=%s",
                installation_id,
                device_type,
                sanitized_name,
            )
        else:
            # Add new entry
            new_device = Device(
                installation_id=installation_id,
                device_name=sanitized_name,
                device_type=device_type,
                push_url=push_url,
                registered_at=now,
                last_seen=now,
            )
            registry.devices.append(new_device)
            logger.info(
                "Device registered: id=%s, type=%s, name=%s",
                installation_id,
                device_type,
                sanitized_name,
            )

        save_devices(devices_file, registry)


async def remove_device(
    devices_file: Path,
    installation_id: str,
) -> bool:
    """
    Remove device by installation_id.

    Returns True if device was found and removed.
    Called when binding is invalid (410 Gone response).

    Args:
        devices_file: Path to devices.json
        installation_id: UUID from app to remove

    Returns:
        True if device was found and removed, False otherwise
    """
    async with get_file_lock():
        registry = load_devices(devices_file)

        # Find and remove device
        original_count = len(registry.devices)
        registry.devices = [d for d in registry.devices if d.installation_id != installation_id]
        removed = len(registry.devices) < original_count

        if removed:
            save_devices(devices_file, registry)
            logger.info("Device unregistered: id=%s", installation_id)
        else:
            logger.warning("Device not found: id=%s", installation_id)

        return removed


async def get_device(
    devices_file: Path,
    installation_id: str,
) -> Device | None:
    """
    Get device by installation_id.

    Args:
        devices_file: Path to devices.json
        installation_id: UUID from app to retrieve

    Returns:
        Device if found, None otherwise
    """
    async with get_file_lock():
        registry = load_devices(devices_file)

        for device in registry.devices:
            if device.installation_id == installation_id:
                return device

        return None


async def list_devices(
    devices_file: Path,
    device_filter: str | None = None,
) -> list[Device]:
    """
    List all devices with optional filtering.

    Args:
        devices_file: Path to devices.json
        device_filter: Filter by device name or type (iphone, ipad, mac)

    Returns:
        List of Device objects matching filter
    """
    async with get_file_lock():
        registry = load_devices(devices_file)

        if not device_filter:
            return registry.devices

        # Filter by device name or type
        filter_lower = device_filter.lower()
        filtered = []
        for device in registry.devices:
            # Match device type
            if device.device_type == filter_lower:
                filtered.append(device)
                continue

            # Match device name (case insensitive)
            if device.device_name and filter_lower in device.device_name.lower():
                filtered.append(device)
                continue

        return filtered
