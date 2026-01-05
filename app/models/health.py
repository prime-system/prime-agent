"""Health check models and types."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class HealthStatus(str, Enum):
    """Health check status values."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ServiceHealth(BaseModel):
    """Health status for a single service."""

    name: str = Field(..., description="Service name")
    status: HealthStatus = Field(..., description="Health status")
    message: str | None = Field(None, description="Status message")
    response_time_ms: float | None = Field(None, description="Response time in milliseconds")
    details: dict = Field(default_factory=dict, description="Additional details")


class HealthCheckResponse(BaseModel):
    """Complete health check response."""

    status: HealthStatus = Field(..., description="Overall status")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")
    version: str = Field(..., description="Application version")
    services: list[ServiceHealth] = Field(default_factory=list, description="Status of each service")

    def is_ready(self) -> bool:
        """
        Check if system is ready to serve traffic.

        Returns:
            True if overall status is healthy or degraded, False if unhealthy
        """
        return self.status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED]
