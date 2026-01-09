#!/usr/bin/env python3
"""
Configuration parser for Prime entrypoint script.

Reads config.yaml and exports values as shell variables.
Environment variables take precedence over config file values.

Usage:
    eval "$(python3 /app/scripts/parse_config.py /app/config.yaml)"

This sets shell variables that can be used in the entrypoint script.
"""

import os
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("export CONFIG_PARSE_ERROR='PyYAML not installed'", file=sys.stderr)
    sys.exit(1)


def get_nested_value(data: dict, *keys: str, default: Any = None) -> Any:
    """
    Get nested dictionary value safely.

    Example:
        get_nested_value(config, 'git', 'enabled', default=False)
    """
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def bool_to_string(value: Any) -> str:
    """Convert boolean to string for shell (true/false)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        # Normalize various boolean string representations
        normalized = value.lower().strip()
        if normalized in ("true", "yes", "1", "on"):
            return "true"
        if normalized in ("false", "no", "0", "off", ""):
            return "false"
    return str(value) if value is not None else ""


def shell_escape(value: str) -> str:
    """Escape value for safe use in shell export."""
    if not value:
        return '""'
    # If value contains special characters, wrap in single quotes
    if any(c in value for c in (' ', '$', '`', '"', "'", '\n', '\t', '\\', '|', '&', ';', '<', '>')):
        # Escape single quotes by ending quote, adding escaped quote, starting quote again
        escaped = value.replace("'", "'\"'\"'")
        return f"'{escaped}'"
    return value


def expand_env_vars(config_str: str) -> str:
    """Expand ${VAR_NAME} placeholders using environment variables."""

    def replace_var(match: re.Match[str]) -> str:
        var_name = match.group(1)
        try:
            return os.environ[var_name]
        except KeyError:
            msg = f"Environment variable '{var_name}' referenced in config.yaml but not set"
            raise KeyError(msg) from None

    lines: list[str] = []
    for line in config_str.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            lines.append(line)
        else:
            lines.append(re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", replace_var, line))

    return "\n".join(lines)


def parse_config(config_path: str) -> dict[str, str]:
    """
    Parse configuration file and return shell variable exports.

    Returns:
        Dictionary of variable names to values (all strings)
    """
    exports = {}

    # Try to load config file
    config = {}
    config_file = Path(config_path)

    if config_file.exists():
        try:
            config_str = config_file.read_text()
            expanded_config = expand_env_vars(config_str)
            config = yaml.safe_load(expanded_config) or {}
        except Exception as e:
            exports['CONFIG_PARSE_ERROR'] = f"Failed to parse {config_path}: {e}"
            return exports
    else:
        exports['CONFIG_PARSE_WARNING'] = f"Config file not found: {config_path}"

    # Git configuration
    git_enabled = get_nested_value(config, 'git', 'enabled', default=False)
    exports['GIT_ENABLED'] = os.environ.get('GIT_ENABLED', bool_to_string(git_enabled))

    repo_url = get_nested_value(config, 'git', 'repo_url', default='')
    exports['VAULT_REPO_URL'] = os.environ.get('VAULT_REPO_URL', repo_url)

    git_user_name = get_nested_value(config, 'git', 'user_name', default='Prime Agent')
    exports['GIT_USER_NAME'] = os.environ.get('GIT_USER_NAME', git_user_name)

    git_user_email = get_nested_value(config, 'git', 'user_email', default='prime@local')
    exports['GIT_USER_EMAIL'] = os.environ.get('GIT_USER_EMAIL', git_user_email)

    # Vault configuration
    vault_path = get_nested_value(config, 'vault', 'path', default='/vault')
    exports['VAULT_PATH'] = os.environ.get('VAULT_PATH', vault_path)

    # Workspace configuration
    workspace_path = get_nested_value(config, 'workspace', 'path', default='/workspace')
    exports['WORKSPACE_PATH'] = os.environ.get('WORKSPACE_PATH', workspace_path)

    # Logging configuration
    log_level = get_nested_value(config, 'logging', 'level', default='INFO')
    exports['LOG_LEVEL'] = os.environ.get('LOG_LEVEL', log_level)

    # Base URL configuration
    base_url = get_nested_value(config, 'base_url', default='')
    exports['BASE_URL'] = os.environ.get('BASE_URL', base_url)

    # Auth configuration
    auth_token_env = os.environ.get('AUTH_TOKEN')
    auth_token = auth_token_env or get_nested_value(config, 'auth', 'token', default='')
    if auth_token:
        exports['AUTH_TOKEN'] = auth_token

    # Storage configuration
    data_path = get_nested_value(config, 'storage', 'data_path', default='/data')
    exports['DATA_PATH'] = os.environ.get('DATA_PATH', data_path)

    return exports


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: parse_config.py <config_file>", file=sys.stderr)
        sys.exit(1)

    config_path = sys.argv[1]
    exports = parse_config(config_path)

    # Check for errors
    if 'CONFIG_PARSE_ERROR' in exports:
        print(f"export CONFIG_PARSE_ERROR={shell_escape(exports['CONFIG_PARSE_ERROR'])}", file=sys.stderr)
        sys.exit(1)

    # Print warning if any (but don't exit)
    if 'CONFIG_PARSE_WARNING' in exports:
        print(f"# Warning: {exports['CONFIG_PARSE_WARNING']}", file=sys.stderr)

    # Output shell variable exports
    for key, value in exports.items():
        if key.startswith('CONFIG_'):
            continue  # Skip internal variables
        escaped_value = shell_escape(value)
        print(f"export {key}={escaped_value}")


if __name__ == '__main__':
    main()
