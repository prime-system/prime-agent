"""Configuration endpoint for server capabilities."""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.config import Settings, get_config_manager
from app.dependencies import verify_token
from app.services.vault import VaultService
from app.version import get_version

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["config"])

# Global services (injected at startup)
_vault_service: VaultService | None = None
_settings: Settings | None = None


def init_services(vault_service: VaultService, settings: Settings) -> None:
    """Initialize services for this module."""
    global _vault_service, _settings
    _vault_service = vault_service
    _settings = settings


def get_services() -> tuple[VaultService, Settings]:
    """Get services dependency."""
    if _vault_service is None or _settings is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Services not initialized",
        )
    return _vault_service, _settings


class FeaturesResponse(BaseModel):
    """Feature flags."""

    git_enabled: bool = Field(description="Whether Git sync is configured and available")
    workspaces_enabled: bool = Field(description="Whether workspace/vault switching is supported")
    custom_process_prompt: bool = Field(description="Whether user has customized the processCapture prompt")


class ServerInfoResponse(BaseModel):
    """Server information."""

    name: str = Field(description="Server name")
    version: str = Field(description="Server version")


class ConfigResponse(BaseModel):
    """Server configuration response."""

    features: FeaturesResponse
    server_info: ServerInfoResponse


@router.get("/config", response_model=ConfigResponse)
async def get_config() -> ConfigResponse:
    """
    Get server configuration and feature flags.

    Returns information about enabled features so clients can
    adapt their UI dynamically.
    """
    vault_service, settings = get_services()
    vault_path = vault_service.vault_path

    # Check if user has created a custom processCapture.md in vault
    # If not, agent will use the default template from app/prompts/
    custom_process_prompt = (
        vault_path / ".claude" / "commands" / "processCapture.md"
    ).exists()

    return ConfigResponse(
        features=FeaturesResponse(
            git_enabled=settings.git_enabled,
            workspaces_enabled=settings.workspaces_enabled,
            custom_process_prompt=custom_process_prompt,
        ),
        server_info=ServerInfoResponse(
            name="Prime",
            version=get_version(),
        ),
    )


class ReloadResponse(BaseModel):
    """Response from config reload endpoint."""

    status: str = Field(description="Status of the reload operation")
    message: str = Field(description="Detailed message about the reload")


@router.post("/config/reload", response_model=ReloadResponse)
async def reload_config(
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
        vault_service, _ = get_services()

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
