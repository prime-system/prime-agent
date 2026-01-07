"""Request/response models for push notification API."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class DeviceRegisterRequest(BaseModel):
    """Device registration request."""

    installation_id: str = Field(..., description="UUID from PrimeMobileApp")
    device_name: str | None = Field(None, description="Device name", max_length=64)
    device_type: Literal["iphone", "ipad", "mac"] = Field("iphone", description="Device type")
    push_url: str = Field(
        ...,
        description="Capability URL (required for new devices, optional for updates)",
    )


class NotificationSendRequest(BaseModel):
    """Push notification send request."""

    device_filter: str | None = Field(
        None,
        description="Optional device filter (name or type: iphone, ipad, mac)",
    )
    title: str = Field(..., description="Notification title", max_length=100)
    body: str = Field(..., description="Notification body", max_length=500)
    data: dict[str, Any] | None = Field(
        None,
        description="Custom data dict (max 2KB)",
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
