"""
Dynamic configuration manager with file modification detection and graceful fallback.

Provides centralized config loading and reloading for both application-level config
(config.yaml) and vault-specific config (.prime.yaml).
"""

import logging
import os
from pathlib import Path
from threading import Lock

import yaml
from pydantic import ValidationError

from app.config import Settings, expand_env_vars

logger = logging.getLogger(__name__)


class ConfigManager:
    """
    Manages application configuration with dynamic reloading.

    Features:
    - Tracks file modification time to detect changes
    - Lazy reloads config before accessing values
    - Maintains fallback config if reload fails
    - Thread-safe with locking
    - Logs all reload events
    """

    def __init__(self, config_path: str | None = None):
        """
        Initialize ConfigManager.

        Args:
            config_path: Path to config.yaml. If None, uses CONFIG_PATH env var or /app/config.yaml
        """
        if config_path is None:
            config_path = os.environ.get("CONFIG_PATH", "/app/config.yaml")

        self.config_path = Path(config_path)
        self._current_settings: Settings | None = None
        self._last_mtime: float | None = None
        self._lock = Lock()

        # Load initial config
        self._load_config()

    def _load_config(self) -> None:
        """
        Load configuration from YAML file.

        Sets both _current_settings and _last_mtime.
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
            logger.warning(f"Config file missing on reload: {msg}")
            return

        try:
            # Read file
            with open(self.config_path) as f:
                config_str = f.read()

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
                new_settings = Settings(**flat_config)  # type: ignore[arg-type]
            except ValidationError as e:
                msg = f"Configuration validation error: {e}"
                if self._current_settings is None:
                    raise
                logger.warning(msg)
                return

            # Validate configs
            try:
                new_settings.validate_git_config()
                new_settings.validate_apn_config()
            except ValueError as e:
                msg = f"Configuration validation error: {e}"
                if self._current_settings is None:
                    raise
                logger.warning(msg)
                return

            # Update settings and mtime
            self._current_settings = new_settings
            self._last_mtime = self.config_path.stat().st_mtime
            logger.info(f"Configuration loaded successfully from {self.config_path}")

        except Exception as e:
            if self._current_settings is None:
                raise
            logger.warning(f"Error loading configuration: {e}")

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

        Handles these scenarios:
        - File exists and mtime changed → True (reload)
        - File created at runtime → True (reload)
        - File deleted/missing → False (keep using last valid config)
        - File unchanged → False (no reload needed)
        """
        file_exists = self.config_path.exists()

        # Case 1: File was loaded before and still exists
        if self._last_mtime is not None and file_exists:
            current_mtime = self.config_path.stat().st_mtime
            return current_mtime != self._last_mtime

        # Case 2: File didn't exist before and now exists (created at runtime)
        if self._last_mtime is None and file_exists:
            logger.info(f"Config file created at runtime: {self.config_path}")
            return True

        # Case 3: File never existed, still doesn't exist
        if self._last_mtime is None and not file_exists:
            return False

        # Case 4: File existed before but now doesn't (deleted at runtime)
        # Keep using last valid config, don't reload
        if self._last_mtime is not None and not file_exists:
            logger.warning(f"Config file was deleted: {self.config_path}")
            return False

        return False

    def get_settings(self) -> Settings:
        """
        Get current settings, reloading if config file has changed.

        Thread-safe. Returns last valid config if reload fails.
        Logs reload events and errors.

        Returns:
            Current Settings instance
        """
        with self._lock:
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

        Thread-safe. Maintains last valid config if reload fails.
        """
        with self._lock:
            logger.info(f"Forcing config reload from {self.config_path}")
            self._load_config()
