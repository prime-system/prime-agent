"""
Agent worker for asynchronous processing of dumps.

This module implements a fire-and-forget worker that processes dumps
in the background, ensuring only one processing run happens at a time.
"""

import asyncio
import logging
import time
from typing import Optional

from app.services.agent import AgentService
from app.services.git import GitError, GitService
from app.services.lock import get_vault_lock
from app.services.logs import LogService

logger = logging.getLogger(__name__)


class AgentWorker:
    """
    Orchestrates agent processing with locking and error handling.

    Design:
    - Fire-and-forget triggering (don't block capture response)
    - Only one worker runs at a time (class-level flag)
    - Shares vault_lock with capture endpoint
    - Creates audit log for every run (success or failure)

    The worker is a singleton initialized at application startup.
    """

    _processing: bool = False  # Class-level flag to prevent concurrent runs
    _instance: Optional["AgentWorker"] = None

    def __init__(
        self,
        agent_service: AgentService,
        git_service: GitService,
        log_service: LogService,
    ):
        """
        Initialize worker (private - use initialize() class method).

        Args:
            agent_service: Service for invoking Claude Agent SDK
            git_service: Service for git operations
            log_service: Service for creating audit logs
        """
        self.agent_service = agent_service
        self.git_service = git_service
        self.log_service = log_service

    @classmethod
    def initialize(
        cls,
        agent_service: AgentService,
        git_service: GitService,
        log_service: LogService,
    ) -> None:
        """
        Initialize the singleton worker instance.

        Called once at application startup in the lifespan context.

        Args:
            agent_service: Service for invoking Claude Agent SDK
            git_service: Service for git operations
            log_service: Service for creating audit logs
        """
        cls._instance = cls(agent_service, git_service, log_service)
        logger.info(
            "Agent worker initialized",
            extra={
                "git_enabled": git_service.enabled,
            },
        )

    @classmethod
    def is_processing(cls) -> bool:
        """
        Check if worker is currently processing.

        Returns:
            True if processing is in progress, False otherwise
        """
        return cls._processing

    @classmethod
    def trigger(cls) -> None:
        """
        Trigger processing if not already running.

        This is fire-and-forget: it creates an async task and returns
        immediately without waiting for completion.

        If processing is already in progress, this is a no-op.
        """
        if cls._instance is None:
            logger.error("Worker not initialized - cannot trigger processing")
            return

        if cls._processing:
            logger.info("Worker already processing, skipping trigger")
            return

        # Fire and forget - create background task
        asyncio.create_task(cls._instance._process())
        logger.info("Worker trigger: background task created")

    async def _process(self) -> None:
        """
        Internal processing method (runs in background).

        Flow:
        1. Set processing flag
        2. Acquire vault_lock (shared with capture)
        3. Pull from git (if enabled)
        4. Invoke agent to process dumps
        5. Create log file
        6. Commit and push all changes (if git enabled)
        7. Release lock and flag

        This method handles all errors and ensures the processing flag
        is always cleared, even if processing fails.
        """
        # Check flag again (race condition guard)
        if AgentWorker._processing:
            logger.warning("Process called but already processing (race condition)")
            return

        # Set processing flag
        AgentWorker._processing = True
        start_time = time.time()
        duration_seconds: float = 0.0
        logger.info("Starting agent processing")

        try:
            vault_lock = get_vault_lock()
            async with vault_lock:
                logger.debug("Acquired vault lock")

                # Pull latest changes (if git enabled)
                if self.git_service.enabled:
                    try:
                        self.git_service.pull()
                        logger.debug("Git pull completed")
                    except GitError as e:
                        logger.error(
                            "Git pull failed",
                            extra={
                                "error": str(e),
                                "error_type": type(e).__name__,
                            },
                        )
                        # Continue anyway - agent might still work with local files

                # Process dumps with agent
                result = await self.agent_service.process_dumps()

                # Calculate duration
                duration_seconds = time.time() - start_time

                # Create audit log
                self.log_service.create_run_log(
                    duration_seconds=duration_seconds,
                    cost_usd=result.get("cost_usd"),
                    error=result.get("error"),
                )

                # Get all changed files from git
                changed_files = self.git_service.get_changed_files()

                # Commit and push if successful
                if result.get("success"):
                    if self.git_service.enabled and changed_files:
                        try:
                            commit_msg = (
                                f"Process: inbox dumps ({len(changed_files)} files changed)"
                            )
                            self.git_service.commit_and_push(commit_msg, changed_files)
                            logger.info(
                                "Processing committed to git",
                                extra={
                                    "files_count": len(changed_files),
                                },
                            )
                        except GitError as e:
                            logger.error(
                                "Git commit and push failed",
                                extra={
                                    "files_count": len(changed_files),
                                    "error": str(e),
                                    "error_type": type(e).__name__,
                                },
                            )
                            # Log is already created locally, not critical
                    cost_usd = result.get("cost_usd")
                    cost_usd_value = cost_usd if cost_usd is not None else 0.0
                    logger.info(
                        "Processing completed successfully",
                        extra={
                            "duration_seconds": round(duration_seconds, 2),
                            "cost_usd": round(cost_usd_value, 4),
                        },
                    )
                else:
                    # Even on failure, commit the log
                    if self.git_service.enabled and changed_files:
                        try:
                            self.git_service.commit_and_push(
                                "Process: failed (see log)", changed_files
                            )
                        except GitError as e:
                            logger.error(
                                "Git commit failed (error log)",
                                extra={
                                    "error": str(e),
                                    "error_type": type(e).__name__,
                                },
                            )
                    logger.error(
                        "Processing failed",
                        extra={
                            "duration_seconds": round(duration_seconds, 2),
                            "error": result.get("error"),
                        },
                    )

        except Exception as e:
            duration_seconds = time.time() - start_time
            logger.exception(
                "Worker processing failed with unexpected exception",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "duration_seconds": round(duration_seconds, 2),
                },
            )
            # Try to create error log if possible
            try:
                self.log_service.create_run_log(
                    duration_seconds=duration_seconds,
                    error=f"Unexpected exception: {e!s}",
                )
                # Try to commit error log
                if self.git_service.enabled:
                    changed_files = self.git_service.get_changed_files()
                    if changed_files:
                        try:
                            self.git_service.commit_and_push(
                                "Process: exception (see log)", changed_files
                            )
                        except GitError:
                            pass  # Best effort
            except Exception as log_error:
                logger.exception(
                    "Failed to create error log",
                    extra={
                        "error": str(log_error),
                        "error_type": type(log_error).__name__,
                    },
                )

        finally:
            # Always clear processing flag
            AgentWorker._processing = False
            logger.info("Agent processing complete (lock released)")
