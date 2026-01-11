import logging
from datetime import datetime
from pathlib import Path

from app.models.vault_config import VaultConfig, load_vault_config

logger = logging.getLogger(__name__)


class VaultService:
    """Manages vault directory structure and paths."""

    def __init__(self, vault_path: str):
        self.vault_path = Path(vault_path)
        self._vault_config: VaultConfig | None = None
        self._config_file_path = Path(vault_path) / ".prime" / "settings.yaml"
        self._last_mtime: float | None = None

    @property
    def vault_config(self) -> VaultConfig:
        """
        Load vault config lazily from .prime/settings.yaml with dynamic reloading.

        Checks if .prime/settings.yaml has been modified since last load and reloads if necessary.
        If reload fails, returns last valid config.
        """
        # Check if config file has changed
        if self._should_reload_vault_config():
            try:
                self._vault_config = load_vault_config(self.vault_path)
                if self._config_file_path.exists():
                    self._last_mtime = self._config_file_path.stat().st_mtime
                logger.debug("Vault config reloaded from .prime/settings.yaml")
            except Exception as e:
                logger.warning(
                    "Failed to reload vault config",
                    extra={
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "config_file": str(self._config_file_path),
                        "vault_path": str(self.vault_path),
                    },
                    exc_info=True,
                )
                # Fall through to return last valid config (or new default if none exists)
                if self._vault_config is None:
                    self._vault_config = load_vault_config(self.vault_path)

        # Initialize if never loaded
        if self._vault_config is None:
            self._vault_config = load_vault_config(self.vault_path)
            if self._config_file_path.exists():
                self._last_mtime = self._config_file_path.stat().st_mtime

        return self._vault_config

    def _should_reload_vault_config(self) -> bool:
        """
        Check if vault config file has been modified, created, or deleted since last load.

        Handles these scenarios:
        - File exists and mtime changed → True (reload)
        - File created at runtime → True (reload)
        - File deleted/missing → False (keep using last valid config)
        - File unchanged → False (no reload needed)
        """
        file_exists = self._config_file_path.exists()

        # Case 1: File was loaded before and still exists
        if self._last_mtime is not None and file_exists:
            current_mtime = self._config_file_path.stat().st_mtime
            return current_mtime != self._last_mtime

        # Case 2: File didn't exist before and now exists (created at runtime)
        if self._last_mtime is None and file_exists:
            logger.info(f"Vault config created at runtime: {self._config_file_path}")
            return True

        # Case 3: File never existed, still doesn't exist
        if self._last_mtime is None and not file_exists:
            return False

        # Case 4: File existed before but now doesn't (deleted at runtime)
        # Keep using last valid config, don't reload
        if self._last_mtime is not None and not file_exists:
            logger.warning(f"Vault config was deleted: {self._config_file_path}")
            return False

        return False

    def reload_vault_config(self) -> None:
        """
        Force reload of vault config (e.g., after config change).

        Thread-safe. Maintains last valid config if reload fails.
        """
        logger.info("Forcing vault config reload")
        self._vault_config = None
        self._last_mtime = None
        # Trigger reload on next access
        _ = self.vault_config

    def ensure_structure(self) -> None:
        """Create vault base directory if it doesn't exist."""
        # Create .prime/ directory for config and logs
        prime_dir = self.vault_path / ".prime"
        prime_dir.mkdir(parents=True, exist_ok=True)

        # Note: All other vault folders are created on-demand:
        # - Daily, Notes, etc. by the Agent when processing captures
        # - .claude/commands/ by users when customizing prompts
        # This keeps the vault clean and allows flexible folder structures.

    def inbox_path(self) -> Path:
        """Return path to Inbox folder (configurable via .prime/settings.yaml)."""
        return self.vault_path / self.vault_config.inbox.folder

    def logs_path(self) -> Path:
        """Return path to Logs folder (configurable via .prime/settings.yaml)."""
        return self.vault_path / self.vault_config.logs.folder

    def get_capture_file(self, dt: datetime, source: str) -> Path:
        """
        Return path for a capture file.

        Each capture gets its own file with a configurable filename pattern.
        Supports optional weekly subfolders for organization.

        Example paths:
        - Without subfolders: Inbox/2026-01-02_12-00-00_iphone.md
        - With subfolders: 07-Inbox/2026-W01/2026-01-02_12-00-00_iphone.md

        Args:
            dt: Timestamp of the capture
            source: Source device (iphone, ipad, mac)
        """
        config = self.vault_config.inbox
        inbox = self.inbox_path()
        iso_cal = dt.isocalendar()

        # Build the base path (with optional weekly subfolder)
        if config.weekly_subfolders:
            subfolder = f"{iso_cal.year}-W{iso_cal.week:02d}"
            inbox = inbox / subfolder

        # Format filename using pattern
        format_params = {
            "year": dt.year,
            "month": f"{dt.month:02d}",
            "day": f"{dt.day:02d}",
            "hour": f"{dt.hour:02d}",
            "minute": f"{dt.minute:02d}",
            "second": f"{dt.second:02d}",
            "source": source,
            "iso_year": iso_cal.year,
            "iso_week": f"{iso_cal.week:02d}",
        }

        filename = config.file_pattern.format(**format_params)

        return inbox / filename

    def get_relative_path(self, absolute_path: Path) -> str:
        """Return path relative to vault root."""
        return str(absolute_path.relative_to(self.vault_path))
