"""Configuration endpoint for server capabilities."""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.config import get_config_manager, settings
from app.dependencies import get_agent_identity_service, get_vault_service, verify_token
from app.services.agent_identity import AgentIdentityService
from app.services.vault import VaultService
from app.version import get_version

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["config"])


class FeaturesResponse(BaseModel):
    """Feature flags."""

    git_enabled: bool = Field(description="Whether Git sync is configured and available")
    workspaces_enabled: bool = Field(description="Whether workspace/vault switching is supported")


class ServerInfoResponse(BaseModel):
    """Server information."""

    name: str = Field(description="Server name")
    version: str = Field(description="Server version")
    prime_agent_id: str = Field(description="Unique persistent agent identifier")


class ConfigResponse(BaseModel):
    """Server configuration response."""

    features: FeaturesResponse
    server_info: ServerInfoResponse


@router.get("/config", response_model=ConfigResponse)
async def get_config(
    agent_identity_service: AgentIdentityService = Depends(get_agent_identity_service),
    _: None = Depends(verify_token),
) -> ConfigResponse:
    """
    Get server configuration and feature flags.

    Returns information about enabled features so clients can
    adapt their UI dynamically.

    Requires authentication token.
    """
    return ConfigResponse(
        features=FeaturesResponse(
            git_enabled=settings.git_enabled,
            workspaces_enabled=settings.workspaces_enabled,
        ),
        server_info=ServerInfoResponse(
            name="Prime",
            version=get_version(),
            prime_agent_id=agent_identity_service.get_cached_identity() or "unknown",
        ),
    )


class ReloadResponse(BaseModel):
    """Response from config reload endpoint."""

    status: str = Field(description="Status of the reload operation")
    message: str = Field(description="Detailed message about the reload")


@router.post("/config/reload", response_model=ReloadResponse)
async def reload_config(
    vault_service: VaultService = Depends(get_vault_service),
    _: None = Depends(verify_token),
) -> ReloadResponse:
    """
    Force immediate reload of application configuration.

    This endpoint triggers a reload of both config.yaml and vault-specific .prime.yaml.
    Requires authentication token.

    Returns:
        Status and message about the reload operation
    """
    try:
        # Reload application config
        config_manager = get_config_manager()
        config_manager.reload()

        # Reload vault config
        vault_service.reload_vault_config()

        logger.info("Configuration reloaded via API endpoint")
        return ReloadResponse(
            status="success",
            message="Configuration reloaded successfully from both config.yaml and .prime.yaml",
        )

    except Exception as e:
        logger.error(f"Error reloading configuration: {e}")
        return ReloadResponse(
            status="error",
            message=f"Error reloading configuration: {e}",
        )
