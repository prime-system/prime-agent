import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.dependencies import verify_token
from app.models.capture import CaptureRequest, CaptureResponse
from app.services.git import GitService
from app.services.inbox import InboxService
from app.services.title_generator import TitleGenerator
from app.services.vault import VaultService

logger = logging.getLogger(__name__)
router = APIRouter()

vault_service: VaultService
git_service: GitService
inbox_service: InboxService
title_generator: TitleGenerator | None = None


def init_services(vault: VaultService, git: GitService, inbox: InboxService) -> None:
    """Initialize module-level services."""
    global vault_service, git_service, inbox_service, title_generator
    vault_service = vault
    git_service = git
    inbox_service = inbox

    # Initialize title generator if needed
    if vault_service.needs_title_generation():
        title_generator = TitleGenerator()
        logger.info("Title generation enabled (pattern contains {title})")


@router.post("/capture", response_model=CaptureResponse)
async def capture(
    request: CaptureRequest,
    background_tasks: BackgroundTasks,
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

    logger.info(f"Capture received: {dump_id}")

    # Generate title if the file pattern requires it
    title = None
    if title_generator:
        try:
            title = await title_generator.generate_title(request.text)
            logger.info(f"Generated title for {dump_id}: {title}")
        except Exception as e:
            logger.warning(f"Title generation failed for {dump_id}: {e}, using fallback")
            # Fallback is handled in title_generator

    inbox_file = vault_service.get_capture_file(
        request.captured_at, request.source.value, title=title
    )
    relative_path = vault_service.get_relative_path(inbox_file)

    try:
        # Write capture to its own file with frontmatter
        content = inbox_service.format_capture_file(request, dump_id)
        inbox_service.write_capture(inbox_file, content)
        logger.info(f"Capture saved locally: {dump_id} -> {relative_path}")
    except OSError as e:
        logger.error(f"Failed to write capture file for {dump_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save capture",
        ) from e

    # Queue git commit and push in background (errors ignored)
    background_tasks.add_task(git_service.auto_commit_and_push)

    return CaptureResponse(
        ok=True,
        inbox_file=relative_path,
        dump_id=dump_id,
    )
