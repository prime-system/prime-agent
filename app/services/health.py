"""Health check service."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from app.models.health import HealthCheckResponse, HealthStatus, ServiceHealth

if TYPE_CHECKING:
    from app.services.git import GitService
    from app.services.vault import VaultService

logger = logging.getLogger(__name__)


class HealthCheckService:
    """Service for checking system health."""

    def __init__(
        self,
        vault_service: VaultService,
        git_service: GitService | None = None,
        version: str = "unknown",
    ) -> None:
        """
        Initialize health check service.

        Args:
            vault_service: VaultService instance
            git_service: GitService instance (optional)
            version: Application version string
        """
        self.vault_service = vault_service
        self.git_service = git_service
        self.version = version

    async def check_vault_health(self) -> ServiceHealth:
        """
        Check vault service health.

        Tests that vault directory exists and is writable.
        """
        start = datetime.utcnow()

        try:
            # Check vault path exists
            vault_path = self.vault_service.vault_path

            if not vault_path.exists():
                return ServiceHealth(
                    name="vault",
                    status=HealthStatus.UNHEALTHY,
                    message="Vault directory does not exist",
                )

            # Check write permission by attempting to create a test file
            test_file = vault_path / ".health_check"
            try:
                test_file.write_text("health_check")
                test_file.unlink()
            except Exception as e:
                return ServiceHealth(
                    name="vault",
                    status=HealthStatus.UNHEALTHY,
                    message=f"Vault not writable: {e}",
                )

            elapsed = (datetime.utcnow() - start).total_seconds() * 1000

            return ServiceHealth(
                name="vault",
                status=HealthStatus.HEALTHY,
                message="Vault accessible and writable",
                response_time_ms=elapsed,
                details={"path": str(vault_path)},
            )

        except Exception as e:
            logger.exception("Vault health check failed")
            return ServiceHealth(
                name="vault",
                status=HealthStatus.UNHEALTHY,
                message=f"Vault check failed: {e}",
            )

    async def check_git_health(self) -> ServiceHealth:
        """
        Check git service health.

        If git is disabled, returns HEALTHY status.
        If git is enabled, tests that repository is accessible.
        """
        if not self.git_service or not self.git_service.enabled:
            return ServiceHealth(
                name="git",
                status=HealthStatus.HEALTHY,
                message="Git disabled",
            )

        start = datetime.utcnow()

        try:
            # Try to get changed files to verify git repo is accessible
            changed_files = self.git_service.get_changed_files()

            elapsed = (datetime.utcnow() - start).total_seconds() * 1000

            return ServiceHealth(
                name="git",
                status=HealthStatus.HEALTHY,
                message="Git repository accessible",
                response_time_ms=elapsed,
                details={"changed_files": len(changed_files)},
            )

        except Exception as e:
            logger.exception("Git health check failed")
            return ServiceHealth(
                name="git",
                status=HealthStatus.DEGRADED,
                message=f"Git check failed: {e}",
            )

    async def check_health(self) -> HealthCheckResponse:
        """
        Perform complete health check.

        Checks all services in parallel and returns overall status.

        Returns:
            HealthCheckResponse with overall status and service details
        """
        # Check all services in parallel for efficiency
        vault_health, git_health = await asyncio.gather(
            self.check_vault_health(),
            self.check_git_health(),
        )

        services = [vault_health, git_health]

        # Determine overall status
        if any(s.status == HealthStatus.UNHEALTHY for s in services):
            overall_status = HealthStatus.UNHEALTHY
        elif any(s.status == HealthStatus.DEGRADED for s in services):
            overall_status = HealthStatus.DEGRADED
        else:
            overall_status = HealthStatus.HEALTHY

        return HealthCheckResponse(
            status=overall_status,
            version=self.version,
            services=services,
        )
