"""API endpoints for Claude slash commands."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from app.dependencies import verify_token
from app.exceptions import VaultError
from app.models.command import CommandDetail, CommandListResponse
from app.services.command import CommandService
from app.services.container import get_container

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/commands", dependencies=[Depends(verify_token)])


def get_command_service() -> CommandService:
    """
    Dependency to get command service from container.

    Returns:
        CommandService instance

    Raises:
        HTTPException: If container not initialized
    """
    try:
        container = get_container()
        return container.command_service
    except RuntimeError as e:
        raise HTTPException(
            status_code=500, detail="Service container not initialized"
        ) from e


@router.get("", response_model=CommandListResponse)
async def list_commands(
    command_service: CommandService = Depends(get_command_service),
) -> CommandListResponse:
    """
    List all available slash commands.

    Returns commands from:
    - Vault: `.claude/commands/` directory
    - Plugins: (future support)
    - MCP servers: (future support)

    Each command includes:
    - Name (without leading slash)
    - Description
    - Type (vault/plugin/mcp)
    - Namespace (from subdirectory structure)
    - Argument hint (if specified in frontmatter)
    - Path to command file
    """
    try:
        response = command_service.list_commands()
        logger.info(
            "Listed commands",
            extra={
                "total": response.total,
                "vault_commands": response.vault_commands,
            },
        )
        return response
    except VaultError as e:
        logger.error(
            "Failed to list commands",
            extra=e.context,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list commands: {str(e)}",
        ) from e
    except Exception as e:
        logger.exception(
            "Unexpected error listing commands",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        raise HTTPException(
            status_code=500,
            detail="Unexpected error listing commands",
        ) from e


@router.get("/{command_name}", response_model=CommandDetail)
async def get_command_detail(
    command_name: Annotated[
        str, Path(description="Command name (without leading slash)")
    ],
    command_service: CommandService = Depends(get_command_service),
) -> CommandDetail:
    """
    Get detailed information about a specific command.

    Returns:
    - Basic command info (name, description, type, etc.)
    - Frontmatter metadata (allowed-tools, argument-hint, model, etc.)
    - Full markdown content (without frontmatter)
    - Raw file content (including frontmatter)
    - Parsed features:
      - Argument placeholders ($ARGUMENTS, $1, $2, etc.)
      - Bash commands (with `!` prefix)
      - File references (with `@` prefix)

    Args:
        command_name: Name of the command (without leading slash)

    Raises:
        HTTPException: If command not found or cannot be read
    """
    try:
        command_detail = command_service.get_command_detail(command_name)
        if command_detail is None:
            raise HTTPException(
                status_code=404,
                detail=f"Command '{command_name}' not found",
            )

        logger.info(
            "Retrieved command detail",
            extra={
                "command_name": command_name,
                "type": command_detail.info.type.value,
            },
        )
        return command_detail
    except VaultError as e:
        logger.error(
            "Failed to get command detail",
            extra={
                "command_name": command_name,
                **e.context,
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get command: {str(e)}",
        ) from e
    except HTTPException:
        # Re-raise HTTP exceptions (like 404)
        raise
    except Exception as e:
        logger.exception(
            "Unexpected error getting command detail",
            extra={
                "command_name": command_name,
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        raise HTTPException(
            status_code=500,
            detail="Unexpected error getting command detail",
        ) from e
