"""Push notifications API endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import settings
from app.dependencies import get_push_notification_service, verify_token
from app.models.push import (
    DeviceListResponse,
    DeviceRegisterRequest,
    NotificationSendRequest,
    NotificationSendResponse,
    PushResponse,
)
from app.services import device_registry
from app.services.push_notifications import PushNotificationService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["push"])


@router.post("/devices/register", response_model=PushResponse)
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
    push_notification_service: PushNotificationService = Depends(get_push_notification_service),
    _: None = Depends(verify_token),
) -> NotificationSendResponse:
    """
    Send push notification to devices via PrimePushRelay.

    Uses stored push_url (capability URL) to send notifications.
    """
    try:
        summary = await push_notification_service.send_notification(
            title=request.title,
            body=request.body,
            data=request.data,
            device_filter=request.device_filter,
        )
        success = summary.failed == 0

        return NotificationSendResponse(
            success=success,
            sent=summary.sent,
            failed=summary.failed,
            invalid_tokens_removed=summary.invalid_tokens_removed,
            devices=summary.device_results,
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
