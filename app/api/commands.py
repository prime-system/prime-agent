"""API endpoints for Claude slash commands."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.dependencies import verify_token
from app.exceptions import VaultError
from app.models.command import (
    CommandDetail,
    CommandListResponse,
    CommandRunStatusResponse,
    TriggerCommandRequest,
    TriggerCommandResponse,
)
from app.services.command_run_manager import RunStatus

if TYPE_CHECKING:
    from app.services.agent import AgentService
    from app.services.command import CommandService
    from app.services.command_run_manager import CommandRunManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/commands", dependencies=[Depends(verify_token)])


def get_command_service() -> CommandService:
    """
    Dependency to get command service from container.

    Returns:
        CommandService instance

    Raises:
        HTTPException: If container not initialized
    """
    try:
        from app.services import container as container_module

        container = container_module.get_container()
        return container.command_service
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail="Service container not initialized") from e


def get_command_run_manager() -> CommandRunManager:
    """
    Dependency to get command run manager from container.

    Returns:
        CommandRunManager instance

    Raises:
        HTTPException: If container not initialized
    """
    try:
        from app.services import container as container_module

        container = container_module.get_container()
        return container.command_run_manager
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail="Service container not initialized") from e


def get_agent_service() -> AgentService:
    """
    Dependency to get agent service from container.

    Returns:
        AgentService instance

    Raises:
        HTTPException: If container not initialized
    """
    try:
        from app.services import container as container_module

        container = container_module.get_container()
        return container.agent_service
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail="Service container not initialized") from e


@router.get("", response_model=CommandListResponse, response_model_by_alias=False)
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
        logger.exception(
            "Failed to list commands",
            extra=e.context,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list commands: {e!s}",
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


@router.get("/{command_name}", response_model=CommandDetail, response_model_by_alias=False)
async def get_command_detail(
    command_name: Annotated[str, Path(description="Command name (without leading slash)")],
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
        logger.exception(
            "Failed to get command detail",
            extra={
                "command_name": command_name,
                **e.context,
            },
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get command: {e!s}",
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


@router.post("/{command_name}/trigger", response_model=TriggerCommandResponse)
async def trigger_command(
    command_name: Annotated[str, Path(description="Command name (without leading slash)")],
    request: TriggerCommandRequest,
    command_service: CommandService = Depends(get_command_service),
    agent_service: AgentService = Depends(get_agent_service),
    run_manager: CommandRunManager = Depends(get_command_run_manager),
) -> TriggerCommandResponse:
    """
    Manually trigger a slash command and return a run ID for polling.

    Validates that the command exists, then starts a background task to execute it.
    Output is captured in memory and can be retrieved via the status endpoint.

    Args:
        command_name: Name of the command (without leading slash, can include namespace)
        request: Request with optional arguments string

    Returns:
        Response with run_id and poll_url for status/output retrieval

    Raises:
        HTTPException: If command not found or validation fails
    """
    # Validate command name format
    if command_name.startswith("/") or re.search(r"\s", command_name):
        raise HTTPException(
            status_code=400,
            detail="Command name must not start with '/' or contain whitespace",
        )

    # Verify command exists
    commands = command_service.list_commands()
    command_exists = any(
        command_name in {cmd.name, f"{cmd.namespace}:{cmd.name}"} for cmd in commands.commands
    )

    if not command_exists:
        logger.warning(
            "Attempted to trigger unknown command",
            extra={"command_name": command_name},
        )
        raise HTTPException(
            status_code=404,
            detail=f"Command '{command_name}' not found",
        )

    # Create run
    run_id = await run_manager.create_run(command_name)

    # Define event handler to capture output
    async def event_handler(event_type: str, data: dict[str, Any]) -> None:
        await run_manager.append_event(run_id, event_type, data)

    # Create background task to execute command
    async def execute_command() -> None:
        try:
            await run_manager.update_status(run_id, RunStatus.RUNNING)

            result = await agent_service.run_command(
                command_name,
                arguments=request.arguments,
                event_handler=event_handler,
            )

            # Update final status
            if result["success"]:
                await run_manager.update_status(
                    run_id,
                    RunStatus.COMPLETED,
                    cost_usd=result["cost_usd"],
                    duration_ms=result["duration_ms"],
                )
            else:
                await run_manager.update_status(
                    run_id,
                    RunStatus.ERROR,
                    error=result["error"],
                    cost_usd=result["cost_usd"],
                    duration_ms=result["duration_ms"],
                )

        except Exception as e:
            logger.exception(
                "Command execution failed",
                extra={
                    "run_id": run_id,
                    "command_name": command_name,
                    "error": str(e),
                },
            )
            await run_manager.update_status(
                run_id,
                RunStatus.ERROR,
                error=str(e),
            )

    # Start background task
    task = asyncio.create_task(execute_command())
    await run_manager.set_task(run_id, task)

    logger.info(
        "Triggered command run",
        extra={
            "run_id": run_id,
            "command_name": command_name,
        },
    )

    return TriggerCommandResponse(
        run_id=run_id,
        status="started",
        poll_url=f"/api/v1/commands/runs/{run_id}",
    )


@router.get("/runs/{run_id}", response_model=CommandRunStatusResponse)
async def get_command_run_status(
    run_id: Annotated[str, Path(description="Run ID returned from trigger endpoint")],
    after: Annotated[
        int | None, Query(description="Return only events after this event_id")
    ] = None,
    run_manager: CommandRunManager = Depends(get_command_run_manager),
) -> CommandRunStatusResponse:
    """
    Get status and output events for a command run.

    Use the `after` query parameter to implement polling:
    - First call: GET /commands/runs/{run_id}
    - Subsequent calls: GET /commands/runs/{run_id}?after={next_cursor}

    The response includes:
    - Current status (started, running, completed, error)
    - Events since the cursor (text chunks, tool calls, thinking, completion)
    - next_cursor for the next poll (-1 if no events emitted yet)
    - dropped_before: first event_id that was evicted from buffer

    Args:
        run_id: Run identifier from trigger response
        after: Optional event_id cursor for polling

    Returns:
        Run status with events and metadata

    Raises:
        HTTPException: If run not found or expired
    """
    status = await run_manager.get_run_status(run_id, after_event_id=after)

    if status is None:
        logger.warning(
            "Attempted to get status for unknown run",
            extra={"run_id": run_id},
        )
        raise HTTPException(
            status_code=404,
            detail=f"Run '{run_id}' not found or expired",
        )

    return CommandRunStatusResponse(**status)
