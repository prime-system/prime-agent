import logging
from datetime import datetime, timezone
from pathlib import Path

import git

logger = logging.getLogger(__name__)


class GitError(Exception):
    """Git operation failed."""


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
    ):
        self.vault_path = Path(vault_path)
        self.enabled = enabled
        self.repo_url = repo_url
        self.user_name = user_name
        self.user_email = user_email
        self._repo: git.Repo | None = None

    def initialize(self) -> None:
        """
        Initialize vault repository (if Git is enabled).

        Git-enabled:
          - If .git doesn't exist: clone from repo_url
          - If .git exists: open existing repo
          - Configure git user for commits

        Local-only:
          - No-op (logs info message)
        """
        if not self.enabled:
            logger.info("Git disabled - running in local-only mode")
            return

        if not self.repo_url:
            msg = "Git enabled but VAULT_REPO_URL not configured"
            raise GitError(msg)

        git_dir = self.vault_path / ".git"

        if not git_dir.exists():
            logger.info(f"Cloning vault from {self.repo_url}")
            self._repo = git.Repo.clone_from(self.repo_url, self.vault_path)
        else:
            logger.info(f"Opening existing vault at {self.vault_path}")
            self._repo = git.Repo(self.vault_path)

        # Configure commit author
        with self._repo.config_writer() as config:
            config.set_value("user", "name", self.user_name)
            config.set_value("user", "email", self.user_email)

    def pull(self) -> None:
        """
        Pull latest changes from origin (if Git is enabled).

        Local-only: No-op
        """
        if not self.enabled:
            return

        if self._repo is None:
            msg = "Repository not initialized"
            raise GitError(msg)

        try:
            origin = self._repo.remotes.origin
            origin.pull()
            logger.debug("Git pull completed")
        except git.GitCommandError as e:
            logger.error(f"Git pull failed: {e}")
            msg = f"Pull failed: {e}"
            raise GitError(msg) from e

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
            # Get untracked and modified files
            changed = []

            # Modified and staged files
            for item in self._repo.index.diff(None):
                changed.append(item.a_path)

            # Untracked files
            changed.extend(self._repo.untracked_files)

            return changed
        except git.GitCommandError as e:
            logger.warning(f"Failed to get changed files: {e}")
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
            logger.debug(f"Git disabled - skipping commit: {message}")
            return

        if self._repo is None:
            msg = "Repository not initialized"
            raise GitError(msg)

        try:
            # Stage specified files
            self._repo.index.add(paths)

            # Commit
            self._repo.index.commit(message)
            logger.debug(f"Committed: {message}")

        except git.GitCommandError as e:
            logger.error(f"Git commit failed: {e}")
            msg = f"Commit failed: {e}"
            raise GitError(msg) from e

    def push(self) -> None:
        """
        Push local commits to remote (if Git is enabled).

        Local-only: No-op
        """
        if not self.enabled:
            return

        if self._repo is None:
            msg = "Repository not initialized"
            raise GitError(msg)

        try:
            origin = self._repo.remotes.origin
            origin.push()
            logger.debug("Git push completed")
        except git.GitCommandError as e:
            logger.error(f"Git push failed: {e}")
            msg = f"Push failed: {e}"
            raise GitError(msg) from e

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
        Non-blocking on errors (returns False instead of raising).

        Returns:
            True if commit+push succeeded or git disabled, False on error

        Local-only: Returns True (no-op)
        """
        if not self.enabled:
            logger.debug("Git disabled - skipping auto-commit")
            return True

        if self._repo is None:
            logger.warning("Repository not initialized - skipping auto-commit")
            return False

        try:
            # Check if there are any changes
            changed_files = self.get_changed_files()
            if not changed_files:
                logger.debug("No changes to auto-commit")
                return True

            # Create commit message with timestamp
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            message = f"Agent: Auto-commit at {timestamp}"

            # Commit and push all changed files
            self.commit_and_push(message, changed_files)
            logger.info(f"✓ Auto-committed {len(changed_files)} files")
            return True

        except GitError as e:
            logger.warning(f"Auto-commit failed (non-blocking): {e}")
            return False
        except Exception as e:
            logger.exception("Unexpected error during auto-commit")
            return False
