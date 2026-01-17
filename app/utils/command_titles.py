"""Utilities for formatting command titles."""

from __future__ import annotations

import re


def format_command_title(command_name: str) -> str:
    """Format a command name into a readable title."""
    cleaned = re.sub(r"[_:-]+", " ", command_name)
    words: list[str] = []
    for token in cleaned.split():
        parts = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\\d+", token)
        words.extend(parts or [token])
    return " ".join(word.lower().capitalize() for word in words)
