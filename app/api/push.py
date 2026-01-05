"""Push notifications API endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import settings
from app.dependencies import verify_token
from app.models.push import (
    DeviceListResponse,
    NotificationSendRequest,
    NotificationSendResponse,
    PushResponse,
    RegisterRequest,
    UnregisterRequest,
)
from app.services import push_tokens
from app.services.apn_service import APNService

logger = logging.getLogger(__name__)
router = APIRouter()

apn_service: APNService | None = None


def init_services(apn: APNService | None = None) -> None:
    """Initialize module-level services."""
    global apn_service
    apn_service = apn


@router.post("/push/register", response_model=PushResponse)
async def register_device(
    request: RegisterRequest,
    _: None = Depends(verify_token),
) -> PushResponse:
    """
    Register or update device token for push notifications.

    Validates token format, sanitizes device name, and stores in devices.json.
    If token already exists, updates last_seen and device_name.
    """
    try:
        push_tokens.add_or_update_token(
            tokens_file=settings.apn_devices_file,
            token=request.token,
            device_type=request.device_type,
            device_name=request.device_name,
            environment=request.environment,
        )

        logger.info("Device registered: token=...%s, type=%s", request.token[-6:], request.device_type)
        return PushResponse(success=True, message="Device registered successfully")
    except ValueError as e:
        # Invalid token format
        logger.warning("Invalid token registration attempt: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except OSError as e:
        # File system error
        logger.error("Failed to save device token: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register device",
        ) from e


@router.delete("/push/unregister", response_model=PushResponse)
async def unregister_device(
    request: UnregisterRequest,
    _: None = Depends(verify_token),
) -> PushResponse:
    """
    Remove device token from push notifications.

    Returns success=true even if token was not found (idempotent).
    """
    try:
        removed = push_tokens.remove_token(
            tokens_file=settings.apn_devices_file,
            token=request.token,
        )

        if removed:
            logger.info("Device unregistered: token=...%s", request.token[-6:])
            return PushResponse(success=True, message="Device unregistered successfully")

        return PushResponse(success=False, message="Token not found")
    except OSError as e:
        logger.error("Failed to remove device token: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to unregister device",
        ) from e


@router.post("/notifications/send", response_model=NotificationSendResponse)
async def send_notification(
    request: NotificationSendRequest,
    _: None = Depends(verify_token),
) -> NotificationSendResponse:
    """
    Send push notification to devices.

    Supports filtering by device ID, device type/name, and environment.
    Auto-removes invalid tokens and returns detailed per-device status.

    Requires APNs to be enabled in configuration.
    """
    if not apn_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Push notifications are not enabled",
        )

    try:
        result = await apn_service.send_to_all(
            title=request.title,
            body=request.body,
            data=request.data,
            priority=request.priority,
            sound=request.sound,
            badge=request.badge,
            device_filter=request.device_filter,
            environment_filter=request.environment,
        )

        # Convert result dict to NotificationSendResponse
        return NotificationSendResponse(
            success=result["success"],
            sent=result["sent"],
            failed=result["failed"],
            invalid_tokens_removed=result["invalid_tokens_removed"],
            devices=[
                {
                    "name": d["name"],
                    "status": d["status"],
                    "error": d.get("error"),
                }
                for d in result["devices"]
            ],
        )

    except Exception as e:
        logger.error("Failed to send notification: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send notification: {e!s}",
        ) from e


@router.get("/devices", response_model=DeviceListResponse)
async def list_devices(
    device_filter: str | None = None,
    environment: str | None = None,
    _: None = Depends(verify_token),
) -> DeviceListResponse:
    """
    List registered devices with optional filtering.

    Query parameters:
    - device_filter: Filter by device name or type (iphone, ipad, mac)
    - environment: Filter by environment (development or production)
    """
    if not apn_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Push notifications are not enabled",
        )

    try:
        devices = apn_service.list_devices(
            device_filter=device_filter,
            environment_filter=environment,  # type: ignore[arg-type]
        )

        return DeviceListResponse(
            total=len(devices),
            devices=devices,
        )

    except Exception as e:
        logger.error("Failed to list devices: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list devices",
        ) from e
