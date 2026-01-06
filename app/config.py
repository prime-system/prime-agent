from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import yaml
from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


def expand_env_vars(config_str: str) -> str:
    """
    Expand environment variables in the format ${VAR_NAME} within a YAML string.
    Skips expansion in YAML comments (lines starting with #).

    Args:
        config_str: YAML configuration string potentially containing ${VAR_NAME} placeholders

    Returns:
        YAML string with all ${VAR_NAME} placeholders expanded to environment variable values

    Raises:
        KeyError: If a referenced environment variable is not set
    """
    def replace_var(match: re.Match[str]) -> str:
        var_name = match.group(1)
        try:
            return os.environ[var_name]
        except KeyError:
            msg = f"Environment variable '{var_name}' referenced in config.yaml but not set"
            raise KeyError(msg) from None

    # Process line by line to skip YAML comments
    lines = []
    for line in config_str.split('\n'):
        # Skip expansion in comment lines (first non-whitespace char is #)
        stripped = line.lstrip()
        if stripped.startswith('#'):
            lines.append(line)
        else:
            lines.append(re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", replace_var, line))

    return '\n'.join(lines)


def load_config_from_yaml(config_path: str | None = None) -> dict:
    """
    Load YAML configuration file and expand environment variables.

    Args:
        config_path: Path to config.yaml file. If None, uses CONFIG_PATH environment variable.
                     Defaults to /app/config.yaml if neither is set.

    Returns:
        Dictionary containing parsed and validated configuration

    Raises:
        FileNotFoundError: If config file is not found
        yaml.YAMLError: If YAML file is invalid
        KeyError: If referenced environment variable is not set
    """
    if config_path is None:
        config_path = os.environ.get("CONFIG_PATH", "/app/config.yaml")

    config_file = Path(config_path)
    if not config_file.exists():
        msg = (
            f"Configuration file not found at {config_path}\n"
            f"Please ensure config.yaml is mounted or copied into /app directory.\n"
            f"Use CONFIG_PATH environment variable to override location."
        )
        raise FileNotFoundError(msg)

    # Read the YAML file
    with open(config_file) as f:
        config_str = f.read()

    # Expand environment variables
    try:
        expanded_config = expand_env_vars(config_str)
    except KeyError as e:
        msg = f"Error expanding environment variables in config.yaml: {e}"
        raise ValueError(msg) from None

    # Parse YAML
    try:
        config_dict = yaml.safe_load(expanded_config)
    except yaml.YAMLError as e:
        msg = f"Invalid YAML in config.yaml: {e}"
        raise ValueError(msg) from None

    if not isinstance(config_dict, dict):
        msg = "config.yaml must contain a YAML mapping/dictionary at root level"
        raise ValueError(msg)

    return config_dict


def _get_cors_origins_from_base_url(base_url: str | None, environment: str) -> list[str]:
    """
    Derive CORS allowed origins from BASE_URL configuration.

    Args:
        base_url: The base URL of the application (e.g., https://app.example.com)
        environment: The deployment environment (development or production)

    Returns:
        List of allowed CORS origins automatically derived from base_url
    """
    origins: list[str] = []

    if base_url:
        # Add the configured base URL
        origins.append(base_url.rstrip("/"))

    # In development, also allow common localhost aliases for local testing
    if environment == "development":
        dev_origins = [
            "http://localhost:3000",
            "http://localhost:8000",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:8000",
        ]
        # Add dev origins that aren't already in the list
        for origin in dev_origins:
            if origin not in origins:
                origins.append(origin)

    return origins


# Build trigger: v4
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,  # Disable .env file loading for Docker
        case_sensitive=False,  # Match environment variables case-insensitively
    )

    # Vault configuration
    vault_path: str = "/vault"

    # Workspace configuration
    workspace_path: str = "/workspace"
    workspaces_enabled: bool = False  # Enable workspace/vault switching

    # Base URL configuration
    base_url: str | None = None  # Base URL of the application (e.g., https://app.example.com)

    # Git configuration (all optional)
    git_enabled: bool = False  # Git toggle (default: false for safe local dev)
    vault_repo_url: str | None = None  # Required only if git_enabled=true
    git_user_name: str = "Prime Agent"
    git_user_email: str = "prime@local"
    git_auth_method: str = "ssh"  # "ssh" or "https"

    # Security
    auth_token: str  # Required
    environment: str = "development"  # Environment mode (development or production)

    # CORS configuration (auto-derived from base_url, no explicit config needed)
    cors_enabled: bool = True
    cors_allowed_origins: list[str] = Field(default=[])
    cors_allowed_methods: list[str] = Field(
        default=["POST", "GET", "OPTIONS"]
    )
    cors_allowed_headers: list[str] = Field(
        default=["Authorization", "Content-Type"]
    )

    # Agent configuration
    anthropic_api_key: str  # Required for Claude Agent SDK
    anthropic_base_url: str | None = None  # Optional custom API endpoint
    agent_model: str  # Required agent model for chat
    agent_max_budget_usd: float = 2.0  # Safety limit per processing run

    # API timeouts (in seconds)
    anthropic_timeout_seconds: int = Field(
        default=1800,
        description="Timeout for Anthropic API calls (includes long agent operations)",
    )
    git_timeout_seconds: int = Field(
        default=30,
        description="Timeout for Git operations (clone, pull, push)",
    )

    # Observability
    log_level: str = "INFO"

    # Data directory for persistent storage
    data_path: str = "/data"  # Persistent data storage (not vault-managed)
    apn_devices_file: Path = Field(
        default=Path("/data/apn/devices.json"),
        description="Path to APNs device tokens file (for backward compatibility)",
    )

    @field_validator("vault_repo_url", mode="after")
    @classmethod
    def validate_vault_repo_url(cls, v: str | None, info) -> str | None:
        """Validate that git.repo_url is set when git.enabled=true."""
        if info.data.get("git_enabled") and not v:
            msg = "git.enabled=true requires git.repo_url to be set in config.yaml"
            raise ValueError(msg)
        return v

    def validate_git_config(self) -> None:
        """Validate Git configuration consistency (called explicitly after creation)."""
        if self.git_enabled and not self.vault_repo_url:
            msg = "git.enabled=true requires git.repo_url to be set in config.yaml"
            raise ValueError(msg)

    def validate_cors_config(self) -> None:
        """Validate CORS configuration for security.

        Ensures:
        - All production origins use HTTPS
        - At least one origin is configured if CORS is enabled in production
        """
        if not self.cors_enabled:
            return

        # Production: ensure all origins are HTTPS
        if self.environment == "production":
            if not self.cors_allowed_origins:
                msg = (
                    "Production environment has no CORS origins configured.\n"
                    "Set base_url in config.yaml (e.g., base_url: https://app.example.com)\n"
                    "CORS origins are automatically derived from base_url."
                )
                raise ValueError(msg)

            # Validate all production origins are HTTPS
            for origin in self.cors_allowed_origins:
                if not origin.startswith("https://"):
                    msg = f"CORS origin must be HTTPS in production: {origin}"
                    raise ValueError(msg)


def _build_settings_from_yaml() -> Settings:
    """Load settings from YAML config file with environment variable expansion."""
    try:
        config_dict = load_config_from_yaml()
    except (FileNotFoundError, ValueError) as e:
        print(f"Configuration error: {e}")
        raise

    # Flatten nested YAML structure to environment variable format
    # config.yaml uses nested structure, but Pydantic expects flat env vars
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

    # Base URL configuration
    if "base_url" in config_dict:
        flat_config["base_url"] = config_dict.get("base_url")

    # Environment mode
    environment = config_dict.get("environment", "development")
    flat_config["environment"] = environment

    # CORS configuration - auto-derive from base_url (simplified!)
    if "cors" in config_dict and isinstance(config_dict["cors"], dict):
        flat_config["cors_enabled"] = config_dict["cors"].get("enabled", True)
        # Only parse explicit overrides (for advanced use cases)
        if "allowed_origins" in config_dict["cors"]:
            flat_config["cors_allowed_origins"] = config_dict["cors"]["allowed_origins"]
        if "allowed_methods" in config_dict["cors"]:
            flat_config["cors_allowed_methods"] = config_dict["cors"]["allowed_methods"]
        if "allowed_headers" in config_dict["cors"]:
            flat_config["cors_allowed_headers"] = config_dict["cors"]["allowed_headers"]
    else:
        flat_config["cors_enabled"] = True

    # If cors_allowed_origins not explicitly set, derive from base_url
    if "cors_allowed_origins" not in flat_config:
        base_url = flat_config.get("base_url")
        flat_config["cors_allowed_origins"] = _get_cors_origins_from_base_url(base_url, environment)

    # Data directory
    if "storage" in config_dict and isinstance(config_dict["storage"], dict):
        flat_config["data_path"] = config_dict["storage"].get("data_path", "/data")

    # Create Settings object
    try:
        settings_obj = Settings(**flat_config)
        # Validate CORS configuration
        settings_obj.validate_cors_config()
        return settings_obj
    except ValidationError as e:
        print(f"Configuration validation error: {e}")
        raise


# Initialize global config manager for dynamic reloading
from app.services.config_manager import ConfigManager


class _SettingsProxy:
    """
    Proxy to Settings that enables dynamic reloading.

    This allows the module-level `settings` object to check for file changes
    on every attribute access and reload if necessary, while maintaining
    compatibility with existing code that accesses settings directly.
    """

    def __init__(self, config_manager: ConfigManager):
        object.__setattr__(self, "_config_manager", config_manager)

    def __getattr__(self, name: str) -> object:
        """Get attribute from current settings, reloading if necessary."""
        config_manager = object.__getattribute__(self, "_config_manager")
        current_settings = config_manager.get_settings()
        return getattr(current_settings, name)

    def __setattr__(self, name: str, value: object) -> None:
        """Prevent attribute assignment on proxy."""
        if name == "_config_manager":
            object.__setattr__(self, name, value)
        else:
            msg = "Settings are read-only; use ConfigManager.reload() to reload from disk"
            raise AttributeError(msg)


_config_manager = ConfigManager()
settings = _SettingsProxy(_config_manager)  # type: ignore[assignment]


def get_config_manager() -> ConfigManager:
    """Get the global ConfigManager instance for explicit reloads."""
    return _config_manager
