"""Service for sending push notifications via PrimePushRelay."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from app.models.push import DeviceResult
from app.services import device_registry

if TYPE_CHECKING:
    from pathlib import Path

    from app.services.relay_client import PrimePushRelayClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PushSendSummary:
    """Summary of a push notification send attempt."""

    sent: int
    failed: int
    invalid_tokens_removed: int
    device_results: list[DeviceResult]


class PushNotificationService:
    """Encapsulates device registry lookup and relay delivery."""

    def __init__(self, devices_file: Path, relay_client: PrimePushRelayClient) -> None:
        self.devices_file = devices_file
        self.relay_client = relay_client

    async def send_notification(
        self,
        *,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        device_filter: str | None = None,
    ) -> PushSendSummary:
        """
        Send a push notification to registered devices.

        Args:
            title: Notification title
            body: Notification body
            data: Optional data payload
            device_filter: Optional device filter (name or type)

        Returns:
            Summary of send results.
        """
        devices = await device_registry.list_devices(
            devices_file=self.devices_file,
            device_filter=device_filter,
        )

        if not devices:
            logger.info(
                "No registered devices for push notification",
                extra={"device_filter": device_filter},
            )
            return PushSendSummary(
                sent=0,
                failed=0,
                invalid_tokens_removed=0,
                device_results=[],
            )

        sent = 0
        failed = 0
        invalid_tokens_removed = 0
        device_results: list[DeviceResult] = []

        for device in devices:
            device_name = device.device_name or device.device_type

            try:
                queued = await self.relay_client.send_push(
                    push_url=device.push_url,
                    title=title,
                    body=body,
                    data=data,
                )

                if queued:
                    sent += 1
                    device_results.append(DeviceResult(name=device_name, status="sent", error=None))
                else:
                    failed += 1
                    device_results.append(
                        DeviceResult(name=device_name, status="failed", error="Not queued")
                    )

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 410:
                    await device_registry.remove_device(
                        self.devices_file,
                        device.installation_id,
                    )
                    invalid_tokens_removed += 1
                    device_results.append(
                        DeviceResult(
                            name=device_name,
                            status="invalid_binding",
                            error="Binding no longer valid (removed)",
                        )
                    )
                    logger.info(
                        "Device removed due to invalid binding",
                        extra={"installation_id": device.installation_id},
                    )
                else:
                    failed += 1
                    device_results.append(
                        DeviceResult(name=device_name, status="failed", error=str(e))
                    )
                    logger.error(
                        "Failed to send to device",
                        extra={
                            "installation_id": device.installation_id,
                            "status_code": e.response.status_code,
                            "error_type": type(e).__name__,
                        },
                    )

            except Exception as e:
                failed += 1
                device_results.append(DeviceResult(name=device_name, status="failed", error=str(e)))
                logger.exception(
                    "Failed to send to device",
                    extra={
                        "installation_id": device.installation_id,
                        "error_type": type(e).__name__,
                    },
                )

        logger.info(
            "Push notification send completed",
            extra={
                "sent": sent,
                "failed": failed,
                "invalid_tokens_removed": invalid_tokens_removed,
            },
        )

        return PushSendSummary(
            sent=sent,
            failed=failed,
            invalid_tokens_removed=invalid_tokens_removed,
            device_results=device_results,
        )
