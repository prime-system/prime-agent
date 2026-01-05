"""Request/response models for push notification API."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    """Device token registration request."""

    token: str = Field(..., description="APNs device token (64 hex characters)")
    device_type: Literal["iphone", "ipad", "mac"] = Field(..., description="Device type")
    device_name: str | None = Field(
        None,
        description="Optional human-readable device name",
        max_length=64,
    )
    environment: Literal["development", "production"] = Field(
        ...,
        description="APNs environment",
    )


class UnregisterRequest(BaseModel):
    """Device token unregistration request."""

    token: str = Field(..., description="APNs device token to remove")


class NotificationSendRequest(BaseModel):
    """Push notification send request."""

    device_id: str | None = Field(
        None,
        description="Optional device ID to send to (send to all if omitted)",
    )
    device_filter: str | None = Field(
        None,
        description="Optional device filter (name or type: iphone, ipad, mac)",
    )
    environment: Literal["development", "production"] | None = Field(
        None,
        description="Optional environment filter (development or production)",
    )
    title: str = Field(..., description="Notification title")
    body: str = Field(..., description="Notification body")
    priority: Literal["high", "normal"] = Field(
        "normal",
        description="Notification priority",
    )
    sound: str = Field(
        "default",
        description="Notification sound",
    )
    badge: int | None = Field(
        None,
        description="Badge count (optional)",
    )
    data: dict[str, Any] | None = Field(
        None,
        description="Custom data dict",
    )


class DeviceResult(BaseModel):
    """Result for a single device notification."""

    name: str = Field(..., description="Device name or type")
    status: str = Field(..., description="Status (sent, failed, invalid_token, etc)")
    error: str | None = Field(None, description="Error message if failed")


class NotificationSendResponse(BaseModel):
    """Push notification send response."""

    success: bool = Field(..., description="Overall success (all devices succeeded)")
    sent: int = Field(..., description="Number of successful sends")
    failed: int = Field(..., description="Number of failed sends")
    invalid_tokens_removed: int = Field(
        ...,
        description="Number of invalid tokens auto-removed",
    )
    devices: list[DeviceResult] = Field(..., description="Per-device results")


class DeviceListResponse(BaseModel):
    """Response for listing devices."""

    total: int = Field(..., description="Total devices")
    devices: list[dict[str, Any]] = Field(..., description="Device list with truncated tokens")


class PushResponse(BaseModel):
    """Push API response."""

    success: bool
    message: str
