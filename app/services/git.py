import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import git

from app.exceptions import GitError

logger = logging.getLogger(__name__)

__all__ = ["GitError", "GitService"]


class GitService:
    """
    Handles Git operations for the vault.

    Can be instantiated in disabled mode for local-only vaults.
    """

    def __init__(
        self,
        vault_path: str,
        enabled: bool = False,
        repo_url: str | None = None,
        user_name: str = "Prime Agent",
        user_email: str = "prime@local",
        timeout_seconds: int = 30,
    ):
        self.vault_path = Path(vault_path)
        self.enabled = enabled
        self.repo_url = repo_url
        self.user_name = user_name
        self.user_email = user_email
        self.timeout_seconds = timeout_seconds
        self._repo: git.Repo | None = None

    def initialize(self) -> None:
        """
        Initialize vault repository (if Git is enabled).

        Git-enabled:
          - If .git doesn't exist: clone from repo_url (with timeout)
          - If .git exists: open existing repo
          - Configure git user for commits

        Local-only:
          - No-op (logs info message)

        Raises:
            GitError: If clone times out or other git operations fail
        """
        if not self.enabled:
            logger.info("Git disabled - running in local-only mode")
            return

        if not self.repo_url:
            msg = "Git enabled but VAULT_REPO_URL not configured"
            raise GitError(
                msg,
                context={
                    "operation": "initialize",
                    "enabled": self.enabled,
                    "vault_path": str(self.vault_path),
                },
            )

        git_dir = self.vault_path / ".git"

        if not git_dir.exists():
            logger.info(
                "Cloning vault from repository",
                extra={
                    "repo_url": self.repo_url,
                    "timeout_seconds": self.timeout_seconds,
                    "vault_path": str(self.vault_path),
                },
            )
            try:
                self._repo = git.Repo.clone_from(
                    self.repo_url,
                    self.vault_path,
                    env={"GIT_TERMINAL_PROMPT": "0"},  # Prevent interactive prompts
                )
            except subprocess.TimeoutExpired as e:
                msg = f"Git clone timed out after {self.timeout_seconds}s"
                context = {
                    "operation": "clone",
                    "timeout_seconds": self.timeout_seconds,
                    "repo_url": self.repo_url,
                    "vault_path": str(self.vault_path),
                }
                logger.error(
                    "Git clone timed out",
                    extra=context,
                )
                raise GitError(msg, context=context) from e
            except git.GitCommandError as e:
                context = {
                    "operation": "clone",
                    "repo_url": self.repo_url,
                    "vault_path": str(self.vault_path),
                    "error": str(e),
                    "error_type": type(e).__name__,
                }
                logger.exception(
                    "Git clone failed",
                    extra=context,
                )
                msg = f"Failed to clone repository: {e}"
                raise GitError(msg, context=context) from e
        else:
            logger.info(
                "Opening existing vault",
                extra={
                    "vault_path": str(self.vault_path),
                },
            )
            self._repo = git.Repo(self.vault_path)

        # Configure commit author
        with self._repo.config_writer() as config:
            config.set_value("user", "name", self.user_name)
            config.set_value("user", "email", self.user_email)

    def pull(self) -> None:
        """
        Pull latest changes from origin (if Git is enabled).

        Local-only: No-op

        Raises:
            GitError: If pull operation fails or times out
        """
        if not self.enabled:
            return

        if self._repo is None:
            msg = "Repository not initialized"
            raise GitError(
                msg,
                context={
                    "operation": "pull",
                    "enabled": self.enabled,
                    "vault_path": str(self.vault_path),
                },
            )

        try:
            origin = self._repo.remotes.origin
            # GitPython doesn't support direct timeout, so we use git_command_timeout env var
            with self._repo.git.custom_environment(GIT_TERMINAL_PROMPT="0"):
                origin.pull()
            logger.debug("Git pull completed")
        except subprocess.TimeoutExpired as e:
            msg = f"Git pull timed out after {self.timeout_seconds}s"
            context = {
                "operation": "pull",
                "timeout_seconds": self.timeout_seconds,
                "vault_path": str(self.vault_path),
            }
            logger.error(
                "Git pull timed out",
                extra=context,
            )
            raise GitError(msg, context=context) from e
        except git.GitCommandError as e:
            context = {
                "operation": "pull",
                "error": str(e),
                "error_type": type(e).__name__,
                "vault_path": str(self.vault_path),
            }
            logger.exception(
                "Git pull failed",
                extra=context,
            )
            msg = f"Pull failed: {e}"
            raise GitError(msg, context=context) from e

    def get_changed_files(self) -> list[str]:
        """
        Get list of changed files (modified, added, or deleted).

        Returns:
            List of paths relative to vault root

        Local-only: Returns empty list
        """
        if not self.enabled or self._repo is None:
            return []

        try:
            # Modified and staged files
            changed = [item.a_path for item in self._repo.index.diff(None) if item.a_path]

            # Untracked files
            changed.extend(self._repo.untracked_files)

            return changed
        except git.GitCommandError as e:
            logger.warning(
                "Failed to get changed files",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            return []

    def commit(self, message: str, paths: list[str]) -> None:
        """
        Stage files and commit (if Git is enabled).

        Args:
            message: Commit message
            paths: List of paths relative to vault root

        Local-only: No-op
        """
        if not self.enabled:
            logger.debug(
                "Git disabled - skipping commit",
                extra={
                    "commit_message": message,
                },
            )
            return

        if self._repo is None:
            msg = "Repository not initialized"
            raise GitError(
                msg,
                context={
                    "operation": "commit",
                    "enabled": self.enabled,
                    "vault_path": str(self.vault_path),
                    "message": message,
                    "files_count": len(paths),
                },
            )

        try:
            # Stage specified files
            self._repo.index.add(paths)

            # Commit
            self._repo.index.commit(message)
            logger.debug(
                "Git commit completed",
                extra={
                    "commit_message": message,
                    "files_count": len(paths),
                },
            )

        except git.GitCommandError as e:
            context = {
                "operation": "commit",
                "message": message,
                "files_count": len(paths),
                "error": str(e),
                "error_type": type(e).__name__,
                "vault_path": str(self.vault_path),
            }
            logger.exception(
                "Git commit failed",
                extra=context,
            )
            msg = f"Commit failed: {e}"
            raise GitError(msg, context=context) from e

    def push(self) -> None:
        """
        Push local commits to remote (if Git is enabled).

        Local-only: No-op

        Raises:
            GitError: If push operation fails or times out
        """
        if not self.enabled:
            return

        if self._repo is None:
            msg = "Repository not initialized"
            raise GitError(
                msg,
                context={
                    "operation": "push",
                    "enabled": self.enabled,
                    "vault_path": str(self.vault_path),
                },
            )

        try:
            origin = self._repo.remotes.origin
            # GitPython doesn't support direct timeout, so we use git_command_timeout env var
            with self._repo.git.custom_environment(GIT_TERMINAL_PROMPT="0"):
                origin.push()
            logger.debug("Git push completed")
        except subprocess.TimeoutExpired as e:
            msg = f"Git push timed out after {self.timeout_seconds}s"
            context = {
                "operation": "push",
                "timeout_seconds": self.timeout_seconds,
                "vault_path": str(self.vault_path),
            }
            logger.error(
                "Git push timed out",
                extra=context,
            )
            raise GitError(msg, context=context) from e
        except git.GitCommandError as e:
            context = {
                "operation": "push",
                "error": str(e),
                "error_type": type(e).__name__,
                "vault_path": str(self.vault_path),
            }
            logger.exception(
                "Git push failed",
                extra=context,
            )
            msg = f"Push failed: {e}"
            raise GitError(msg, context=context) from e

    def commit_and_push(self, message: str, paths: list[str]) -> None:
        """
        Stage files, commit, and push (if Git is enabled).

        Args:
            message: Commit message
            paths: List of paths relative to vault root

        Local-only: No-op
        """
        self.commit(message, paths)
        self.push()

    def auto_commit_and_push(self) -> bool:
        """
        Auto-commit all changes and push (if Git is enabled).

        Creates a commit with timestamp for all changed files.
        Called as background task after capture. Errors are logged but
        don't block the capture response.

        Returns:
            True if commit+push succeeded or git disabled, False on error

        Local-only: Returns True (no-op)

        Raises:
            GitError: On git operation failures (caller should log)
        """
        if not self.enabled:
            logger.debug("Git disabled - skipping auto-commit")
            return True

        if self._repo is None:
            msg = "Repository not initialized - cannot auto-commit"
            context = {
                "operation": "auto_commit_and_push",
                "enabled": self.enabled,
                "vault_path": str(self.vault_path),
            }
            logger.error("Repository not initialized", extra=context)
            raise GitError(msg, context=context)

        try:
            # Check if there are any changes
            changed_files = self.get_changed_files()
            if not changed_files:
                logger.debug("No changes to auto-commit")
                return True

            logger.debug(
                "Auto-committing changes",
                extra={
                    "files_count": len(changed_files),
                },
            )

            # Create commit message with timestamp
            timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
            message = f"Agent: Auto-commit at {timestamp}"

            # Commit and push all changed files
            self.commit_and_push(message, changed_files)
            logger.info(
                "Auto-commit and push completed",
                extra={
                    "files_count": len(changed_files),
                    "timestamp": timestamp,
                },
            )
            return True

        except GitError as e:
            logger.exception(
                "Auto-commit and push failed",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            raise
        except Exception as e:
            error_msg = f"Unexpected error during auto-commit: {e}"
            context = {
                "operation": "auto_commit_and_push",
                "error": str(e),
                "error_type": type(e).__name__,
                "vault_path": str(self.vault_path),
            }
            logger.exception(
                "Unexpected error during auto-commit",
                extra=context,
            )
            raise GitError(error_msg, context=context) from e
