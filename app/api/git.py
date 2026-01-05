"""Git operations API endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.dependencies import get_git_service, verify_token
from app.services.git import GitError, GitService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/git", dependencies=[Depends(verify_token)])


class GitStatusResponse(BaseModel):
    """Response model for git status."""

    enabled: bool = Field(description="Whether git is enabled")
    changed_files: list[str] = Field(description="List of changed files (relative paths)")
    count: int = Field(description="Number of changed files")


class CommitRequest(BaseModel):
    """Request model for git commit."""

    message: str = Field(description="Commit message")
    paths: list[str] | None = Field(
        default=None,
        description="Optional list of specific paths to commit (default: all changed files)",
    )


class GitOperationResponse(BaseModel):
    """Response model for git operations."""

    success: bool = Field(description="Whether operation succeeded")
    message: str = Field(description="Result message")


@router.get("/status", response_model=GitStatusResponse)
async def get_status(
    git_service: GitService = Depends(get_git_service),
) -> GitStatusResponse:
    """
    Get list of uncommitted files.

    Returns list of files that have been modified, added, or deleted
    but not yet committed to git.
    """
    if not git_service.enabled:
        return GitStatusResponse(
            enabled=False,
            changed_files=[],
            count=0,
        )

    try:
        changed_files = git_service.get_changed_files()
        return GitStatusResponse(
            enabled=True,
            changed_files=changed_files,
            count=len(changed_files),
        )
    except Exception as e:
        logger.exception("Failed to get git status")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get git status: {e}",
        ) from e


@router.post("/pull", response_model=GitOperationResponse)
async def pull_changes(
    git_service: GitService = Depends(get_git_service),
) -> GitOperationResponse:
    """
    Pull latest changes from remote repository.

    Performs git pull with rebase to fetch and integrate remote changes.
    """
    if not git_service.enabled:
        return GitOperationResponse(
            success=False,
            message="Git is disabled",
        )

    try:
        git_service.pull()
        return GitOperationResponse(
            success=True,
            message="Successfully pulled changes from remote",
        )
    except GitError as e:
        logger.error(f"Git pull failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e


@router.post("/commit", response_model=GitOperationResponse)
async def commit_changes(
    request: CommitRequest,
    git_service: GitService = Depends(get_git_service),
) -> GitOperationResponse:
    """
    Commit changes to local repository.

    If paths is not specified, commits all changed files.
    Note: This does NOT push to remote - use /push endpoint separately.
    """
    if not git_service.enabled:
        return GitOperationResponse(
            success=False,
            message="Git is disabled",
        )

    try:
        # Get paths to commit (all changed files if not specified)
        paths = request.paths
        if paths is None:
            paths = git_service.get_changed_files()

        if not paths:
            return GitOperationResponse(
                success=False,
                message="No files to commit",
            )

        # Commit (but don't push)
        git_service.commit(request.message, paths)

        return GitOperationResponse(
            success=True,
            message=f"Successfully committed {len(paths)} file(s) (not pushed yet)",
        )
    except GitError as e:
        logger.error(f"Git commit failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e


@router.post("/push", response_model=GitOperationResponse)
async def push_changes(
    git_service: GitService = Depends(get_git_service),
) -> GitOperationResponse:
    """
    Push committed changes to remote repository.

    Pushes all local commits to the configured remote (origin).
    """
    if not git_service.enabled:
        return GitOperationResponse(
            success=False,
            message="Git is disabled",
        )

    try:
        # Push commits to remote
        git_service.push()

        return GitOperationResponse(
            success=True,
            message="Successfully pushed changes to remote",
        )
    except GitError as e:
        logger.error(f"Git push failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.error(f"Git push failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Push failed: {e}",
        ) from e


@router.post("/sync", response_model=GitOperationResponse)
async def sync_changes(
    git_service: GitService = Depends(get_git_service),
) -> GitOperationResponse:
    """
    Full sync: auto-commit all changes, then pull and push.

    This is a convenience endpoint that:
    1. Auto-commits all changed files (if any)
    2. Pulls latest changes from remote
    3. Pushes local commits to remote

    Returns combined status of all operations.
    """
    if not git_service.enabled:
        return GitOperationResponse(
            success=False,
            message="Git is disabled",
        )

    try:
        # Auto-commit if there are changes
        success = git_service.auto_commit_and_push()

        if success:
            return GitOperationResponse(
                success=True,
                message="Successfully synced all changes",
            )
        else:
            return GitOperationResponse(
                success=False,
                message="Sync failed - check logs for details",
            )
    except Exception as e:
        logger.error(f"Git sync failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync failed: {e}",
        ) from e
