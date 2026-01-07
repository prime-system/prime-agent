"""Push notifications API endpoints."""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, status

from app.config import settings
from app.dependencies import get_relay_client, verify_token
from app.models.push import (
    DeviceListResponse,
    DeviceRegisterRequest,
    DeviceResult,
    NotificationSendRequest,
    NotificationSendResponse,
    PushResponse,
)
from app.services import device_registry
from app.services.relay_client import PrimePushRelayClient

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/devices/register", response_model=PushResponse)
async def register_device(
    request: DeviceRegisterRequest,
    _: None = Depends(verify_token),
) -> PushResponse:
    """
    Register device with push_url from PrimeMobileApp.

    Called by PrimeMobileApp after it creates a binding with PrimePushRelay.
    The app passes the push_url (capability URL) to store.

    For existing devices, push_url is optional (updates device name only).
    For new devices, push_url is required.
    """
    try:
        # Store device with push_url in registry
        await device_registry.add_or_update_device(
            devices_file=settings.apn_devices_file,
            installation_id=request.installation_id,
            device_name=request.device_name,
            device_type=request.device_type,
            push_url=request.push_url,
        )

        logger.info(
            "Device registered",
            extra={"installation_id": request.installation_id},
        )

        return PushResponse(success=True, message="Device registered successfully")

    except ValueError as e:
        # Missing push_url for new device registration
        logger.warning(
            "Device registration validation failed",
            extra={
                "installation_id": request.installation_id,
                "error": str(e),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    except Exception as e:
        logger.exception(
            "Failed to register device",
            extra={
                "installation_id": request.installation_id,
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register device",
        ) from e


@router.post("/notifications/send", response_model=NotificationSendResponse)
async def send_notification(
    request: NotificationSendRequest,
    relay_client: PrimePushRelayClient = Depends(get_relay_client),
    _: None = Depends(verify_token),
) -> NotificationSendResponse:
    """
    Send push notification to devices via PrimePushRelay.

    Uses stored push_url (capability URL) to send notifications.
    """
    try:
        # Load devices from registry
        devices = await device_registry.list_devices(
            devices_file=settings.apn_devices_file,
            device_filter=request.device_filter,
        )

        sent = 0
        failed = 0
        invalid_tokens_removed = 0
        device_results: list[DeviceResult] = []

        # Send to each device via their push_url
        for device in devices:
            device_name = device.device_name or device.device_type

            try:
                queued = await relay_client.send_push(
                    push_url=device.push_url,
                    title=request.title,
                    body=request.body,
                    data=request.data,
                )

                if queued:
                    sent += 1
                    device_results.append(
                        DeviceResult(name=device_name, status="sent", error=None)
                    )
                else:
                    failed += 1
                    device_results.append(
                        DeviceResult(name=device_name, status="failed", error="Not queued")
                    )

            except httpx.HTTPStatusError as e:
                # Handle specific HTTP errors
                if e.response.status_code == 410:
                    # Gone - invalid binding, remove device
                    await device_registry.remove_device(
                        settings.apn_devices_file,
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
                            "error": str(e),
                        },
                    )

            except Exception as e:
                logger.error(
                    "Failed to send to device",
                    extra={
                        "installation_id": device.installation_id,
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                )
                failed += 1
                device_results.append(
                    DeviceResult(name=device_name, status="failed", error=str(e))
                )

        success = failed == 0

        logger.info(
            "Notification send completed",
            extra={
                "sent": sent,
                "failed": failed,
                "invalid_tokens_removed": invalid_tokens_removed,
            },
        )

        return NotificationSendResponse(
            success=success,
            sent=sent,
            failed=failed,
            invalid_tokens_removed=invalid_tokens_removed,
            devices=device_results,
        )

    except Exception as e:
        logger.exception(
            "Failed to send notifications",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send notifications: {e!s}",
        ) from e


@router.get("/devices", response_model=DeviceListResponse)
async def list_devices(
    device_filter: str | None = None,
    _: None = Depends(verify_token),
) -> DeviceListResponse:
    """List registered devices with optional filtering."""
    try:
        devices = await device_registry.list_devices(
            devices_file=settings.apn_devices_file,
            device_filter=device_filter,
        )

        # Return devices with push_url redacted (security)
        safe_devices = [
            {
                "installation_id": d.installation_id,
                "device_name": d.device_name,
                "device_type": d.device_type,
                "registered_at": d.registered_at,
                "last_seen": d.last_seen,
                # Never return push_url (contains secret)
            }
            for d in devices
        ]

        logger.debug(
            "Listed devices",
            extra={"count": len(safe_devices), "filter": device_filter},
        )

        return DeviceListResponse(
            total=len(safe_devices),
            devices=safe_devices,
        )

    except Exception as e:
        logger.exception(
            "Failed to list devices",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list devices",
        ) from e
