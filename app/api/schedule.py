"""Schedule endpoints for running slash commands via .prime/schedule.yaml."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path

from app.dependencies import get_schedule_service, verify_token
from app.models.schedule import ScheduleCancelResponse, ScheduleStatusResponse

if TYPE_CHECKING:
    from app.services.schedule import ScheduleService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/schedule", tags=["schedule"], dependencies=[Depends(verify_token)]
)


@router.get("/status", response_model=ScheduleStatusResponse, response_model_by_alias=False)
async def get_schedule_status(
    schedule_service: ScheduleService = Depends(get_schedule_service),
) -> ScheduleStatusResponse:
    """Get schedule status and job runtime information."""
    return await schedule_service.get_status()


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=ScheduleCancelResponse,
    response_model_by_alias=False,
)
async def cancel_job(
    job_id: Annotated[str, Path(description="Scheduled job id")],
    schedule_service: ScheduleService = Depends(get_schedule_service),
) -> ScheduleCancelResponse:
    """Cancel a running scheduled job."""
    if not await schedule_service.has_job(job_id):
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    cancelled = await schedule_service.cancel_job(job_id)
    status: Literal["cancelled", "not_running"] = "cancelled" if cancelled else "not_running"

    logger.info(
        "Schedule job cancel requested",
        extra={"job_id": job_id, "status": status},
    )

    return ScheduleCancelResponse(status=status)
