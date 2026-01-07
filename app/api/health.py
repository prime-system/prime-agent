"""Health check endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Response, status

from app.dependencies import get_health_service, verify_token
from app.models.health import HealthCheckResponse

if TYPE_CHECKING:
    from app.services.health import HealthCheckService

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """
    Simple health check for liveness probe.

    Returns 200 if service is running. No authentication required.
    Use this for Kubernetes liveness probes.

    Returns:
        Simple status object indicating service is alive
    """
    return {"status": "ok"}


@router.get("/health/ready", response_model=HealthCheckResponse)
async def health_ready(
    response: Response,
    health_service: HealthCheckService = Depends(get_health_service),
) -> HealthCheckResponse:
    """
    Readiness check with service verification.

    Verifies vault, git, and APNs availability. No authentication required.
    Use this for Kubernetes readiness probes.

    Returns:
        - 200 if system is healthy or degraded
        - 503 if system is unhealthy

    Returns:
        HealthCheckResponse with overall status and service details
    """
    health_check = await health_service.check_health()

    if not health_check.is_ready():
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return health_check


@router.get("/health/detailed", response_model=HealthCheckResponse)
async def health_detailed(
    health_service: HealthCheckService = Depends(get_health_service),
    _: None = Depends(verify_token),
) -> HealthCheckResponse:
    """
    Detailed health check (requires authentication).

    Returns complete health status of all services with detailed information.
    Requires valid bearer token for authentication.

    Returns:
        HealthCheckResponse with complete service details
    """
    return await health_service.check_health()
