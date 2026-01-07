import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.dependencies import get_git_service, get_inbox_service, get_vault_service, verify_token
from app.exceptions import InboxError, VaultError
from app.models.capture import CaptureRequest, CaptureResponse
from app.services.background_tasks import safe_background_task
from app.services.git import GitService
from app.services.inbox import InboxService
from app.services.title_generator import TitleGenerator
from app.services.vault import VaultService
from app.utils.error_handling import format_exception_for_response

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/capture", response_model=CaptureResponse)
async def capture(
    request: CaptureRequest,
    background_tasks: BackgroundTasks,
    vault_service: VaultService = Depends(get_vault_service),
    git_service: GitService = Depends(get_git_service),
    inbox_service: InboxService = Depends(get_inbox_service),
    _: None = Depends(verify_token),
) -> CaptureResponse:
    """
    Accept a raw thought capture (non-blocking).

    Flow:
    1. Generate dump_id from captured_at + source
    2. Generate title if needed (using Claude Haiku)
    3. Determine inbox file path based on vault config
    4. Write capture file with frontmatter (creates directories as needed)
    5. Return response immediately
    6. Commit and push to git in background (errors ignored)

    Note: Processing is triggered manually via the /api/processing/trigger endpoint.
    This ensures the capture endpoint returns instantly without any processing overhead.
    """
    dump_id = inbox_service.generate_dump_id(request.captured_at, request.source.value)

    logger.info(
        "Capture received",
        extra={
            "dump_id": dump_id,
            "source": request.source.value,
        },
    )

    # Generate title if the file pattern requires it
    title = None
    if vault_service.needs_title_generation():
        try:
            title_generator = TitleGenerator()
            title = await title_generator.generate_title(request.text)
            logger.info(
                "Generated title for capture",
                extra={
                    "dump_id": dump_id,
                    "title": title,
                },
            )
        except Exception as e:
            logger.warning(
                "Title generation failed for capture",
                extra={
                    "dump_id": dump_id,
                    "error": str(e),
                },
            )
            # Fallback is handled in title_generator

    inbox_file = vault_service.get_capture_file(
        request.captured_at, request.source.value, title=title
    )
    relative_path = vault_service.get_relative_path(inbox_file)

    try:
        # Write capture to its own file with frontmatter
        content = inbox_service.format_capture_file(request, dump_id)
        inbox_service.write_capture(inbox_file, content)
        logger.info(
            "Capture saved locally",
            extra={
                "dump_id": dump_id,
                "relative_path": relative_path,
                "size_bytes": len(content),
            },
        )
    except (OSError, InboxError, VaultError) as e:
        logger.exception(
            "Failed to write capture file",
            extra={
                "dump_id": dump_id,
                "error": str(e),
                "error_type": type(e).__name__,
                "path": str(inbox_file),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=format_exception_for_response(e),
        ) from e
    except Exception as e:
        logger.exception(
            "Unexpected error during capture",
            extra={
                "dump_id": dump_id,
                "error": str(e),
                "error_type": type(e).__name__,
                "path": str(inbox_file),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "InternalServerError",
                "message": "An unexpected error occurred while saving capture",
            },
        ) from e

    # Queue git commit and push in background with error tracking
    background_tasks.add_task(
        safe_background_task,
        "git_auto_commit",
        git_service.auto_commit_and_push,
    )

    return CaptureResponse(
        ok=True,
        inbox_file=relative_path,
        dump_id=dump_id,
    )
