"""
Utilities for redacting sensitive data from logs and output.

This module provides functions to safely redact credentials and sensitive
information from strings and data structures, preventing accidental exposure
in logs, error messages, and debugging output.
"""

from __future__ import annotations

import re
from typing import Any

# Patterns for detecting sensitive data
SENSITIVE_PATTERNS = {
    "api_key": r"(api[_-]?key|apikey)[=:\s]+([a-zA-Z0-9_-]{20,})",
    "auth_token": r"(auth[_-]?token|token)[=:\s]+([a-zA-Z0-9_-]{20,})",
    "p8_key": r"-----BEGIN [A-Z]+ PRIVATE KEY-----.*?-----END [A-Z]+ PRIVATE KEY-----",
}

# Keys that should always be considered sensitive
SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "auth_token",
    "token",
    "p8_key",
    "apple_p8_key",
    "password",
    "secret",
    "access_token",
    "refresh_token",
    "apple_team_id",
    "apple_key_id",
    "key_id",
    "team_id",
    "git_ssh_key",
    "git_token",
}


def redact_sensitive_data(text: str) -> str:
    """
    Redact sensitive data from string using pattern matching.

    Args:
        text: String potentially containing sensitive data

    Returns:
        String with sensitive patterns replaced with [REDACTED_*] placeholders
    """
    result = text
    for name, pattern in SENSITIVE_PATTERNS.items():
        result = re.sub(
            pattern,
            f"[REDACTED_{name.upper()}]",
            result,
            flags=re.DOTALL | re.IGNORECASE,
        )
    return result


def redact_dict(data: dict[str, Any]) -> dict[str, Any]:
    """
    Create a redacted copy of dictionary, hiding sensitive keys.

    Args:
        data: Dictionary potentially containing sensitive values

    Returns:
        New dictionary with sensitive values replaced with [REDACTED]
    """
    redacted = {}
    for key, value in data.items():
        if key.lower() in SENSITIVE_KEYS:
            redacted[key] = "[REDACTED]"
        elif isinstance(value, dict):
            redacted[key] = redact_dict(value)
        elif isinstance(value, (list, tuple)):
            redacted[key] = [
                redact_dict(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            redacted[key] = value
    return redacted
