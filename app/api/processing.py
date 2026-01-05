"""
Processing API endpoints.

Provides manual control over dump processing:
- POST /trigger - Start processing manually
- GET /status - Check if processing is running and view last run
- GET /queue - List unprocessed dumps
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends

from app.dependencies import get_inbox_service, get_log_service, get_vault_service, verify_token
from app.services.inbox import InboxService
from app.services.logs import LogService
from app.services.vault import VaultService
from app.services.worker import AgentWorker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/processing", tags=["processing"])


@router.post("/trigger")
async def trigger_processing(
    _: None = Depends(verify_token),
) -> dict[str, str]:
    """
    Manually trigger processing of unprocessed dumps.

    This starts the agent worker in the background. If processing is already
    in progress, this returns a status indicating that.

    Returns:
        {"status": "started"} if processing was triggered
        {"status": "already_running"} if processing is in progress
    """
    if AgentWorker.is_processing():
        logger.info("Processing trigger requested but already running")
        return {
            "status": "already_running",
            "message": "Processing already in progress",
        }

    AgentWorker.trigger()
    logger.info("Processing triggered manually")
    return {
        "status": "started",
        "message": "Processing started",
    }


@router.get("/status")
async def get_status(
    vault_service: VaultService = Depends(get_vault_service),
    inbox_service: InboxService = Depends(get_inbox_service),
    log_service: LogService = Depends(get_log_service),
    _: None = Depends(verify_token),
) -> dict[str, Any]:
    """
    Get processing status.

    Returns:
        - is_running: Whether processing is currently active
        - last_run: Metadata from most recent processing run (or null)
        - unprocessed_count: Number of dumps waiting to be processed
    """
    is_running = AgentWorker.is_processing()
    last_run = log_service.get_last_run()
    vault_path = vault_service.vault_path
    inbox_folder = vault_service.vault_config.inbox.folder
    unprocessed_dumps = inbox_service.get_unprocessed_dumps(vault_path, inbox_folder)
    unprocessed_count = len(unprocessed_dumps)

    return {
        "is_running": is_running,
        "last_run": last_run,
        "unprocessed_count": unprocessed_count,
    }


@router.get("/queue")
async def get_queue(
    vault_service: VaultService = Depends(get_vault_service),
    inbox_service: InboxService = Depends(get_inbox_service),
    _: None = Depends(verify_token),
) -> dict[str, Any]:
    """
    List all unprocessed dumps in the queue.

    Returns:
        - count: Total number of unprocessed dumps
        - dumps: List of dump metadata with previews
    """
    vault_path = vault_service.vault_path
    inbox_folder = vault_service.vault_config.inbox.folder
    dumps = inbox_service.get_unprocessed_dumps(vault_path, inbox_folder)

    return {
        "count": len(dumps),
        "dumps": dumps,
    }
