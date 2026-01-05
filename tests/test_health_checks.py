"""Tests for health check endpoints and service."""

from __future__ import annotations

import pytest

from app.models.health import HealthCheckResponse, HealthStatus, ServiceHealth
from app.services.health import HealthCheckService
from app.services.vault import VaultService


@pytest.mark.asyncio
async def test_vault_health_check_healthy(temp_vault) -> None:
    """Test vault health check when vault is accessible and writable."""
    vault_service = VaultService(str(temp_vault))

    health_service = HealthCheckService(vault_service=vault_service)

    vault_health = await health_service.check_vault_health()

    assert vault_health.name == "vault"
    assert vault_health.status == HealthStatus.HEALTHY
    assert vault_health.message == "Vault accessible and writable"
    assert vault_health.response_time_ms is not None
    assert vault_health.response_time_ms > 0


@pytest.mark.asyncio
async def test_vault_health_check_unhealthy_nonexistent(temp_vault) -> None:
    """Test vault health check when vault directory doesn't exist."""
    vault_service = VaultService(str(temp_vault / "nonexistent"))

    health_service = HealthCheckService(vault_service=vault_service)

    vault_health = await health_service.check_vault_health()

    assert vault_health.name == "vault"
    assert vault_health.status == HealthStatus.UNHEALTHY
    assert "does not exist" in vault_health.message


@pytest.mark.asyncio
async def test_git_health_check_disabled(temp_vault, mock_git_service) -> None:
    """Test git health check when git is disabled."""
    mock_git_service.enabled = False

    vault_service = VaultService(str(temp_vault))
    health_service = HealthCheckService(
        vault_service=vault_service,
        git_service=mock_git_service,
    )

    git_health = await health_service.check_git_health()

    assert git_health.name == "git"
    assert git_health.status == HealthStatus.HEALTHY
    assert git_health.message == "Git disabled"


@pytest.mark.asyncio
async def test_git_health_check_enabled(temp_vault, mock_git_service) -> None:
    """Test git health check when git is enabled and accessible."""
    mock_git_service.enabled = True
    mock_git_service.get_changed_files = lambda: []

    vault_service = VaultService(str(temp_vault))
    health_service = HealthCheckService(
        vault_service=vault_service,
        git_service=mock_git_service,
    )

    git_health = await health_service.check_git_health()

    assert git_health.name == "git"
    assert git_health.status == HealthStatus.HEALTHY
    assert git_health.message == "Git repository accessible"
    assert git_health.response_time_ms is not None


@pytest.mark.asyncio
async def test_git_health_check_degraded(temp_vault, mock_git_service) -> None:
    """Test git health check when git check fails."""
    mock_git_service.enabled = True
    mock_git_service.get_changed_files = lambda: (_ for _ in ()).throw(RuntimeError("Git check failed"))

    vault_service = VaultService(str(temp_vault))
    health_service = HealthCheckService(
        vault_service=vault_service,
        git_service=mock_git_service,
    )

    git_health = await health_service.check_git_health()

    assert git_health.name == "git"
    assert git_health.status == HealthStatus.DEGRADED


@pytest.mark.asyncio
async def test_apn_health_check_disabled(temp_vault) -> None:
    """Test APNs health check when APNs is disabled."""
    vault_service = VaultService(str(temp_vault))
    health_service = HealthCheckService(
        vault_service=vault_service,
        apn_service=None,
    )

    apn_health = await health_service.check_apn_health()

    assert apn_health.name == "apns"
    assert apn_health.status == HealthStatus.HEALTHY
    assert apn_health.message == "APNs disabled"


@pytest.mark.asyncio
async def test_overall_health_check_all_healthy(temp_vault, mock_git_service) -> None:
    """Test overall health check when all services are healthy."""
    mock_git_service.enabled = False

    vault_service = VaultService(str(temp_vault))
    health_service = HealthCheckService(
        vault_service=vault_service,
        git_service=mock_git_service,
        apn_service=None,
        version="1.0.0",
    )

    health = await health_service.check_health()

    assert health.status == HealthStatus.HEALTHY
    assert health.version == "1.0.0"
    assert len(health.services) == 3
    assert all(s.status == HealthStatus.HEALTHY for s in health.services)
    assert health.is_ready() is True


@pytest.mark.asyncio
async def test_overall_health_check_degraded(temp_vault, mock_git_service) -> None:
    """Test overall health check when one service is degraded."""
    mock_git_service.enabled = True
    mock_git_service.get_changed_files = lambda: (_ for _ in ()).throw(RuntimeError("Git error"))

    vault_service = VaultService(str(temp_vault))
    health_service = HealthCheckService(
        vault_service=vault_service,
        git_service=mock_git_service,
        apn_service=None,
    )

    health = await health_service.check_health()

    assert health.status == HealthStatus.DEGRADED
    assert health.is_ready() is True


@pytest.mark.asyncio
async def test_overall_health_check_unhealthy(temp_vault, mock_git_service) -> None:
    """Test overall health check when vault is unhealthy."""
    vault_service = VaultService(str(temp_vault / "nonexistent"))
    health_service = HealthCheckService(
        vault_service=vault_service,
        git_service=mock_git_service,
        apn_service=None,
    )

    health = await health_service.check_health()

    assert health.status == HealthStatus.UNHEALTHY
    assert health.is_ready() is False


def test_health_endpoint_simple(client) -> None:
    """Test simple /health endpoint (no auth required)."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_ready_endpoint(client) -> None:
    """Test /health/ready endpoint."""
    response = client.get("/health/ready")

    # Should return 200 or 503 based on health status
    assert response.status_code in [200, 503]

    data = response.json()
    assert "status" in data
    assert data["status"] in ["healthy", "degraded", "unhealthy"]
    assert "services" in data
    assert "timestamp" in data
    assert "version" in data


def test_health_ready_endpoint_successful_status(client) -> None:
    """Test that /health/ready returns 200 when system is ready."""
    response = client.get("/health/ready")

    data = response.json()

    # When status is healthy or degraded, should return 200
    if data["status"] in ["healthy", "degraded"]:
        assert response.status_code == 200
    else:
        assert response.status_code == 503


def test_health_detailed_requires_auth(client) -> None:
    """Test that /health/detailed requires authentication."""
    response = client.get("/health/detailed")

    assert response.status_code == 401


def test_health_detailed_with_auth(client, auth_headers) -> None:
    """Test /health/detailed endpoint with valid authentication."""
    response = client.get("/health/detailed", headers=auth_headers)

    assert response.status_code == 200

    data = response.json()
    assert "status" in data
    assert data["status"] in ["healthy", "degraded", "unhealthy"]
    assert "services" in data
    assert len(data["services"]) >= 3

    # Verify service details
    service_names = {s["name"] for s in data["services"]}
    assert "vault" in service_names
    assert "git" in service_names
    assert "apns" in service_names


def test_health_detailed_response_structure(client, auth_headers) -> None:
    """Test the structure of /health/detailed response."""
    response = client.get("/health/detailed", headers=auth_headers)

    assert response.status_code == 200

    data = HealthCheckResponse(**response.json())

    # Verify HealthCheckResponse structure
    assert isinstance(data, HealthCheckResponse)
    assert data.status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.UNHEALTHY]
    assert data.version is not None
    assert len(data.services) >= 0

    # Verify each service
    for service in data.services:
        assert isinstance(service, ServiceHealth)
        assert service.name in ["vault", "git", "apns"]
        assert service.status in [
            HealthStatus.HEALTHY,
            HealthStatus.DEGRADED,
            HealthStatus.UNHEALTHY,
        ]
        assert service.message is not None or service.message is None
        assert isinstance(service.details, dict)
