"""Monitoring endpoints for system health and background tasks."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.dependencies import verify_token
from app.services.background_tasks import get_task_tracker

router = APIRouter(prefix="/api/v1/monitoring", tags=["monitoring"])


@router.get("/background-tasks/status")
async def get_background_task_status(
    _: None = Depends(verify_token),
) -> dict[str, Any]:
    """
    Get status of background tasks.

    Returns:
        {
            "successful_tasks": 42,
            "failed_tasks": 2,
            "recent_failures": [
                {
                    "task": "git_auto_commit",
                    "error": "Push failed: authentication error",
                    "type": "GitError",
                    "timestamp": "2026-01-02T14:30:45.123456"
                }
            ]
        }
    """
    tracker = get_task_tracker()
    return await tracker.get_status()
