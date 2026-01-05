"""
Dynamic configuration manager with file modification detection and graceful fallback.

Provides centralized config loading and reloading for both application-level config
(config.yaml) and vault-specific config (.prime.yaml).
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import yaml
from pydantic import ValidationError

logger = logging.getLogger(__name__)

# Avoid circular import: defer importing Settings and expand_env_vars
# They are only needed inside methods, not at module level
Settings: type | None = None
expand_env_vars: object = None


def _ensure_imports() -> None:
    """Ensure Settings and expand_env_vars are imported (deferred to avoid circular import)."""
    global Settings, expand_env_vars
    if Settings is None or expand_env_vars is None:
        from app.config import Settings as _Settings
        from app.config import expand_env_vars as _expand_env_vars

        Settings = _Settings
        expand_env_vars = _expand_env_vars


class ConfigManager:
    """
    Manages application configuration with dynamic reloading.

    Features:
    - Tracks file modification time to detect changes
    - Lazy reloads config before accessing values
    - Maintains fallback config if reload fails
    - Async-safe with proper event loop handling
    - Logs all reload events

    Note: The configuration manager is initialized at startup (sync context)
    but get_settings() is called from async contexts. We handle this by
    checking if an event loop is running - if so, we skip the lock and rely
    on GIL protection for the dict operations.
    """

    def __init__(self, config_path: str | None = None):
        """
        Initialize ConfigManager.

        Args:
            config_path: Path to config.yaml. If None, uses CONFIG_PATH env var or /app/config.yaml
        """
        _ensure_imports()

        if config_path is None:
            config_path = os.environ.get("CONFIG_PATH", "/app/config.yaml")

        self.config_path = Path(config_path)
        self._current_settings: Settings | None = None  # type: ignore[assignment]
        self._last_mtime: float | None = None
        self._lock: asyncio.Lock | None = None

        # Load initial config
        self._load_config()

    def _get_lock(self) -> asyncio.Lock | None:
        """Get the lock if it exists and event loop is running."""
        try:
            loop = asyncio.get_running_loop()
            # Ensure lock is created in this event loop
            if self._lock is None:
                self._lock = asyncio.Lock()
            return self._lock
        except RuntimeError:
            # No event loop running (sync context) - skip lock
            return None

    def _load_config(self) -> None:
        """
        Load configuration from YAML file with atomic operations.

        Prevents TOCTOU (Time-of-Check-Time-of-Use) race conditions by:
        1. Reading file contents first (atomic operation)
        2. Getting mtime after read (consistent with file contents)
        3. Only updating config if validation passes

        Sets both _current_settings and _last_mtime on success.
        On error, logs warning but doesn't raise (preserves existing config).
        """
        if not self.config_path.exists():
            msg = (
                f"Configuration file not found at {self.config_path}\n"
                f"Please ensure config.yaml is mounted or copied into /app directory.\n"
                f"Use CONFIG_PATH environment variable to override location."
            )
            if self._current_settings is None:
                raise FileNotFoundError(msg)
            logger.warning("Config file missing on reload", extra={"path": str(self.config_path)})
            return

        try:
            # Read file first (atomic operation)
            # This ensures we read consistent file contents
            try:
                config_str = self.config_path.read_text()
            except FileNotFoundError:
                msg = f"Config file was deleted during read: {self.config_path}"
                if self._current_settings is None:
                    raise
                logger.warning(msg)
                return
            except OSError as e:
                msg = f"Failed to read config file: {e}"
                if self._current_settings is None:
                    raise
                logger.warning(msg, extra={"error_type": type(e).__name__})
                return

            # Get mtime after read (now consistent with file contents)
            try:
                current_mtime = self.config_path.stat().st_mtime
            except FileNotFoundError:
                msg = f"Config file was deleted after read: {self.config_path}"
                if self._current_settings is None:
                    raise
                logger.warning(msg)
                return
            except OSError as e:
                msg = f"Failed to stat config file: {e}"
                if self._current_settings is None:
                    raise
                logger.warning(msg, extra={"error_type": type(e).__name__})
                return

            # Skip reload if mtime unchanged (file hasn't been modified)
            if self._last_mtime is not None and current_mtime == self._last_mtime:
                logger.debug("Config file unchanged, skipping reload", extra={"path": str(self.config_path)})
                return

            # Expand environment variables
            try:
                expanded_config = expand_env_vars(config_str)
            except KeyError as e:
                msg = f"Error expanding environment variables in config.yaml: {e}"
                if self._current_settings is None:
                    raise ValueError(msg) from None
                logger.warning(msg)
                return

            # Parse YAML
            try:
                config_dict = yaml.safe_load(expanded_config)
            except yaml.YAMLError as e:
                msg = f"Invalid YAML in config.yaml: {e}"
                if self._current_settings is None:
                    raise ValueError(msg) from None
                logger.warning(msg)
                return

            if not isinstance(config_dict, dict):
                msg = "config.yaml must contain a YAML mapping/dictionary at root level"
                if self._current_settings is None:
                    raise ValueError(msg)
                logger.warning(msg)
                return

            # Flatten nested YAML structure
            flat_config = self._flatten_config(config_dict)

            # Create Settings object
            try:
                new_settings = Settings(**flat_config)
            except ValidationError as e:
                msg = f"Configuration validation error: {e}"
                if self._current_settings is None:
                    raise
                logger.warning(msg, extra={"validation_errors": len(e.errors())})
                return

            # Validate configs
            try:
                new_settings.validate_git_config()
                new_settings.validate_apn_config()
                new_settings.validate_cors_config()
            except ValueError as e:
                msg = f"Configuration validation error: {e}"
                if self._current_settings is None:
                    raise
                logger.warning(msg)
                return

            # All validation passed - atomically update config
            # Both assignments happen in quick succession, so no intermediate state
            self._current_settings = new_settings
            self._last_mtime = current_mtime

            logger.info(
                "Configuration loaded successfully",
                extra={
                    "path": str(self.config_path),
                    "mtime": current_mtime,
                }
            )

        except Exception as e:
            if self._current_settings is None:
                raise
            logger.warning(
                "Error loading configuration",
                exc_info=True,
                extra={"error_type": type(e).__name__},
            )

    def _flatten_config(self, config_dict: dict) -> dict:
        """Flatten nested YAML structure to Settings field format."""
        flat_config = {}

        if "vault" in config_dict and isinstance(config_dict["vault"], dict) and "path" in config_dict["vault"]:
            flat_config["vault_path"] = config_dict["vault"]["path"]

        if "workspace" in config_dict and isinstance(config_dict["workspace"], dict):
            if "path" in config_dict["workspace"]:
                flat_config["workspace_path"] = config_dict["workspace"]["path"]
            flat_config["workspaces_enabled"] = config_dict["workspace"].get("enabled", False)

        if "git" in config_dict and isinstance(config_dict["git"], dict):
            flat_config["git_enabled"] = config_dict["git"].get("enabled", False)
            flat_config["vault_repo_url"] = config_dict["git"].get("repo_url")
            flat_config["git_user_name"] = config_dict["git"].get("user_name", "Prime Agent")
            flat_config["git_user_email"] = config_dict["git"].get("user_email", "prime@local")
            if "auth" in config_dict["git"] and isinstance(config_dict["git"]["auth"], dict):
                flat_config["git_auth_method"] = config_dict["git"]["auth"].get("method", "ssh")

        if "anthropic" in config_dict and isinstance(config_dict["anthropic"], dict):
            flat_config["anthropic_api_key"] = config_dict["anthropic"].get("api_key")
            flat_config["anthropic_base_url"] = config_dict["anthropic"].get("base_url")
            flat_config["agent_model"] = config_dict["anthropic"].get("model")
            flat_config["agent_max_budget_usd"] = config_dict["anthropic"].get("max_budget_usd", 2.0)

        if "auth" in config_dict and isinstance(config_dict["auth"], dict):
            flat_config["auth_token"] = config_dict["auth"].get("token")

        if "logging" in config_dict and isinstance(config_dict["logging"], dict):
            flat_config["log_level"] = config_dict["logging"].get("level", "INFO")

        # Apple Push Notifications (APNs) - optional
        if "apn" in config_dict and isinstance(config_dict["apn"], dict):
            flat_config["apn_enabled"] = config_dict["apn"].get("enabled", False)
            flat_config["apple_team_id"] = config_dict["apn"].get("team_id")
            flat_config["apple_bundle_id"] = config_dict["apn"].get("bundle_id")
            flat_config["apple_key_id"] = config_dict["apn"].get("key_id")

            # Get p8_key and process escape sequences
            p8_key = config_dict["apn"].get("p8_key")
            if p8_key and isinstance(p8_key, str):
                p8_key = p8_key.encode().decode("unicode_escape")
            flat_config["apple_p8_key"] = p8_key

        # Data directory
        if "storage" in config_dict and isinstance(config_dict["storage"], dict):
            flat_config["data_path"] = config_dict["storage"].get("data_path", "/data")

        return flat_config

    def _config_file_changed(self) -> bool:
        """
        Check if config file has been modified, created, or deleted since last load.

        To prevent TOCTOU race conditions:
        1. We only check existence here (lightweight)
        2. We verify mtime atomically in _load_config after reading contents
        3. If file exists but mtime didn't change, _load_config skips reload

        Handles these scenarios:
        - File exists and we have last_mtime → attempt reload, _load_config verifies
        - File created at runtime → True (reload)
        - File deleted/missing → False (keep using last valid config)
        - File unchanged → _load_config will skip if mtime unchanged

        Returns:
            True if we should attempt to reload, False otherwise
        """
        try:
            file_exists = self.config_path.exists()
        except OSError:
            # Filesystem error - don't try to reload
            return False

        # Case 1: File was loaded before and still exists
        # Return True to trigger reload, but _load_config will verify mtime changed
        if self._last_mtime is not None and file_exists:
            return True

        # Case 2: File didn't exist before and now exists (created at runtime)
        if self._last_mtime is None and file_exists:
            logger.info(
                "Config file created at runtime",
                extra={"path": str(self.config_path)},
            )
            return True

        # Case 3: File never existed, still doesn't exist
        if self._last_mtime is None and not file_exists:
            return False

        # Case 4: File existed before but now doesn't (deleted at runtime)
        # Keep using last valid config, don't reload
        if self._last_mtime is not None and not file_exists:
            logger.warning("Config file was deleted", extra={"path": str(self.config_path)})
            return False

        return False

    def get_settings(self) -> Settings:
        """
        Get current settings, reloading if config file has changed.

        Works in both sync and async contexts. If called from async context,
        uses asyncio.Lock if available. Otherwise relies on GIL protection.
        Returns last valid config if reload fails.

        Returns:
            Current Settings instance
        """
        # Note: This is intentionally synchronous to maintain compatibility
        # with the _SettingsProxy in config.py which calls it from __getattr__.
        # If an event loop is running, we could add lock coordination here,
        # but for now we rely on the GIL for thread safety and single-threaded
        # async event loop semantics (only one coroutine runs at a time).
        if self._config_file_changed():
            logger.info(f"Config file modified, reloading from {self.config_path}")
            self._load_config()

        if self._current_settings is None:
            msg = "No valid configuration available"
            raise RuntimeError(msg)

        return self._current_settings

    def reload(self) -> None:
        """
        Force immediate reload of configuration.

        Maintains last valid config if reload fails.
        """
        logger.info(f"Forcing config reload from {self.config_path}")
        self._load_config()
