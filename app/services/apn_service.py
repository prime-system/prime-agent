"""Apple Push Notification service."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from aioapns import APNs, NotificationRequest

from app.services.push_tokens import (
    get_file_lock,
    load_tokens,
    remove_token,
    validate_token_format,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class APNService:
    """Service for sending Apple Push Notifications."""

    def __init__(
        self,
        devices_file: Path,
        key_content: str,
        team_id: str,
        key_id: str,
        bundle_id: str,
        environment: Literal["production", "development"] = "production",
    ) -> None:
        """
        Initialize APNs service.

        Args:
            devices_file: Path to devices.json file
            key_content: Apple P8 key content (not file path)
            team_id: Apple Team ID
            key_id: Apple Key ID
            bundle_id: Bundle ID for PrimeApp
            environment: APNs environment (production or development)

        Raises:
            ValueError: If credentials are invalid
        """
        self.devices_file = devices_file
        self.bundle_id = bundle_id
        self.environment = environment

        try:
            if not key_content or not key_content.strip():
                msg = "APNs key content is empty"
                logger.error(msg)
                raise ValueError(msg)

            logger.info(f"APNs key loaded ({len(key_content)} bytes)")

            self.client = APNs(
                key=key_content,
                key_id=key_id,
                team_id=team_id,
                topic=bundle_id,  # Required for token-based auth
                use_sandbox=(environment == "development"),
            )
            logger.info(
                "APNs client initialized: team_id=%s, key_id=%s, env=%s",
                team_id,
                key_id,
                environment,
            )
        except Exception as e:
            msg = f"Failed to initialize APNs client: {e}"
            logger.error(msg)
            raise ValueError(msg) from e

    async def send_to_device(
        self,
        device_token: str,
        title: str,
        body: str,
        data: dict | None = None,
        priority: Literal["high", "normal"] = "normal",
        sound: str = "default",
        badge: int | None = None,
    ) -> dict:
        """
        Send notification to a single device.

        Args:
            device_token: APNs device token
            title: Notification title
            body: Notification body
            data: Optional custom data dict
            priority: Notification priority (high/normal)
            sound: Notification sound (default: "default")
            badge: Badge count (optional)

        Returns:
            dict with keys: success (bool), status (str), error (str|None)
        """
        if not validate_token_format(device_token):
            logger.warning("Invalid token format: %s...", device_token[:8])
            return {
                "success": False,
                "status": "invalid_token",
                "error": "Invalid token format",
            }

        try:
            # Map priority: high -> 10, normal -> 5
            apns_priority = 10 if priority == "high" else 5

            # Build APS alert structure
            alert = {
                "title": title,
                "body": body,
            }

            aps = {
                "alert": alert,
                "sound": sound,
            }

            # Add badge if provided
            if badge is not None:
                aps["badge"] = badge

            # Build payload
            payload = {"aps": aps}

            # Add custom data if provided
            if data:
                payload.update(data)

            # Create notification request
            request = NotificationRequest(
                device_token=device_token,
                message=payload,
                priority=apns_priority,
            )

            # Send via APNs
            await self.client.send_notification(request)

            logger.info(
                "Notification sent: token=...%s, priority=%s",
                device_token[-6:],
                priority,
            )

            return {
                "success": True,
                "status": "sent",
                "error": None,
            }

        except Exception as e:
            error_str = str(e)
            logger.error(
                "Failed to send notification: token=...%s, error=%s",
                device_token[-6:],
                error_str,
            )

            # Determine if this is a fatal error that should remove token
            should_remove = False
            status = "failed"

            if "BadDeviceToken" in error_str or "invalid" in error_str.lower():
                should_remove = True
                status = "invalid_token"
            elif "Unregistered" in error_str:
                should_remove = True
                status = "unregistered"

            # Auto-remove invalid tokens
            if should_remove:
                try:
                    removed = remove_token(self.devices_file, device_token)
                    if removed:
                        logger.info(
                            "Removed invalid token: token=...%s, reason=%s",
                            device_token[-6:],
                            status,
                        )
                except Exception as cleanup_error:
                    logger.error("Failed to remove invalid token: %s", cleanup_error)

            return {
                "success": False,
                "status": status,
                "error": error_str,
            }

    async def send_to_all(
        self,
        title: str,
        body: str,
        data: dict | None = None,
        priority: Literal["high", "normal"] = "normal",
        sound: str = "default",
        badge: int | None = None,
        device_filter: str | None = None,
        environment_filter: Literal["development", "production"] | None = None,
    ) -> dict:
        """
        Send notification to multiple devices.

        Args:
            title: Notification title
            body: Notification body
            data: Optional custom data dict
            priority: Notification priority
            sound: Notification sound
            badge: Badge count (optional)
            device_filter: Filter by device name or type (iphone, ipad, mac)
            environment_filter: Filter by environment (development/production)

        Returns:
            dict with aggregated results and per-device status
        """
        async with get_file_lock():
            tokens = load_tokens(self.devices_file)

        devices = tokens.get("devices", [])

        # Apply filters
        filtered_devices = []
        for device in devices:
            # Environment filter
            if environment_filter and device.get("environment") != environment_filter:
                continue

            # Device filter (by name or type)
            if device_filter:
                device_name = device.get("device_name", "")
                device_type = device.get("device_type", "")

                # Support multiple types: "iphone,mac"
                if "," in device_filter:
                    types = [t.strip() for t in device_filter.split(",")]
                    if device_type not in types:
                        continue
                # Single name or type match
                elif device_filter not in (device_name, device_type):
                    continue

            filtered_devices.append(device)

        # Send to all filtered devices
        results = {
            "success": True,
            "sent": 0,
            "failed": 0,
            "invalid_tokens_removed": 0,
            "devices": [],
        }

        for device in filtered_devices:
            token = device.get("token")
            if not token:
                continue

            result = await self.send_to_device(
                device_token=token,
                title=title,
                body=body,
                data=data,
                priority=priority,
                sound=sound,
                badge=badge,
            )

            device_result = {
                "name": device.get("device_name") or device.get("device_type", "unknown"),
                "status": result["status"],
            }

            if result["error"]:
                device_result["error"] = result["error"]
                results["failed"] += 1

                # Track auto-removed tokens
                if result["status"] in ("invalid_token", "unregistered"):
                    results["invalid_tokens_removed"] += 1
            else:
                results["sent"] += 1

            results["devices"].append(device_result)

        # Overall success only if all devices succeeded
        results["success"] = results["failed"] == 0

        logger.info(
            "Batch notification complete: sent=%d, failed=%d, removed=%d",
            results["sent"],
            results["failed"],
            results["invalid_tokens_removed"],
        )

        return results

    async def send_by_filter(
        self,
        device_filter: str,
        title: str,
        body: str,
        data: dict | None = None,
        priority: Literal["high", "normal"] = "normal",
        sound: str = "default",
        badge: int | None = None,
    ) -> dict:
        """
        Send notification to devices matching a filter.

        Args:
            device_filter: Device name or type (iphone, ipad, mac, or "iphone,mac")
            title: Notification title
            body: Notification body
            data: Optional custom data dict
            priority: Notification priority
            sound: Notification sound
            badge: Badge count (optional)

        Returns:
            dict with aggregated results
        """
        return await self.send_to_all(
            title=title,
            body=body,
            data=data,
            priority=priority,
            sound=sound,
            badge=badge,
            device_filter=device_filter,
        )

    async def list_devices(
        self,
        device_filter: str | None = None,
        environment_filter: Literal["development", "production"] | None = None,
    ) -> list[dict]:
        """
        List registered devices with optional filtering.

        Args:
            device_filter: Filter by device name or type
            environment_filter: Filter by environment

        Returns:
            List of device dicts
        """
        async with get_file_lock():
            tokens = load_tokens(self.devices_file)

        devices = tokens.get("devices", [])

        # Apply filters
        filtered = []
        for device in devices:
            if environment_filter and device.get("environment") != environment_filter:
                continue

            if device_filter:
                device_name = device.get("device_name", "")
                device_type = device.get("device_type", "")

                if "," in device_filter:
                    types = [t.strip() for t in device_filter.split(",")]
                    if device_type not in types:
                        continue
                elif device_filter not in (device_name, device_type):
                    continue

            # Return safe copy (truncate token)
            safe_device = {
                **device,
                "token": f"...{device['token'][-6:]}",
            }
            filtered.append(safe_device)

        return filtered

    async def get_device_count(self) -> int:
        """Get total count of registered devices."""
        async with get_file_lock():
            tokens = load_tokens(self.devices_file)
        return len(tokens.get("devices", []))
