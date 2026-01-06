"""Client for PrimePushRelay service."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class PushPayload(BaseModel):
    """Push notification payload."""

    title: str
    body: str
    data: dict[str, Any] | None = None


class PrimePushRelayClient:
    """Client for sending push notifications via capability URLs."""

    def __init__(self, timeout_seconds: int = 10) -> None:
        """
        Initialize PrimePushRelay client.

        Args:
            timeout_seconds: Timeout for HTTP requests in seconds
        """
        self.timeout = timeout_seconds

    async def send_push(
        self,
        push_url: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
    ) -> bool:
        """
        Send push notification via capability URL.

        Args:
            push_url: Capability URL (contains push_id and push_secret)
            title: Notification title
            body: Notification body
            data: Optional custom data dict

        Returns:
            True if notification was successfully queued

        Raises:
            httpx.HTTPError: If the request fails
        """
        payload = PushPayload(title=title, body=body, data=data)

        # Extract push_id for logging (NEVER log push_secret)
        push_id = "unknown"
        try:
            # URL format: https://relay.example.com/push/{push_id}/{push_secret}
            parts = push_url.rstrip("/").split("/")
            if len(parts) >= 2:
                push_id = parts[-2]
        except Exception:
            pass  # Use default "unknown" if parsing fails

        logger.debug(
            "Sending push notification",
            extra={
                "push_id": push_id,
                "title": title,
            },
        )

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                push_url,
                json=payload.model_dump(exclude_none=True),
            )

            logger.info(
                "Push notification sent",
                extra={
                    "push_id": push_id,
                    "status_code": response.status_code,
                },
            )

            response.raise_for_status()

            result = response.json()
            return bool(result.get("queued", False))
