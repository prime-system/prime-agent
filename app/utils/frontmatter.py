"""
Robust YAML frontmatter parsing for capture files.

Handles edge cases like multiline values, special characters, missing markers,
and invalid YAML with clear error messages.
"""

from __future__ import annotations

import logging
from typing import Any, NamedTuple

import yaml
from pydantic import ValidationError

from app.models.frontmatter import (
    CaptureFrontmatter,
    CommandFrontmatter,
)

logger = logging.getLogger(__name__)


class FrontmatterError(Exception):
    """Raised when frontmatter parsing fails."""


class ParsedContent(NamedTuple):
    """Result of parsing markdown with frontmatter."""

    frontmatter: dict[str, Any]
    body: str


def parse_frontmatter(content: str) -> ParsedContent:
    """
    Parse YAML frontmatter from markdown content.

    Robust parsing that handles:
    - Missing opening marker
    - Missing closing marker
    - Windows line endings (\\r\\n)
    - Empty frontmatter
    - Multiline YAML values
    - Invalid YAML (logs warning, returns empty dict)

    Args:
        content: Markdown content with optional frontmatter

    Returns:
        ParsedContent with frontmatter dict and body string

    Raises:
        FrontmatterError: If frontmatter validation fails after parsing
    """
    # Normalize line endings
    content = content.replace("\r\n", "\n")

    # Check for frontmatter markers
    if not content.startswith("---"):
        return ParsedContent({}, content)

    # Find closing marker
    lines = content.split("\n")

    # Look for closing --- on its own line
    closing_idx: int | None = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_idx = i
            break

    if closing_idx is None:
        # Missing closing marker - treat as no frontmatter
        logger.warning(
            "Frontmatter missing closing marker",
            extra={
                "content_length": len(content),
            },
        )
        return ParsedContent({}, content)

    # Extract frontmatter and body
    frontmatter_lines = lines[1:closing_idx]
    body_lines = lines[closing_idx + 1 :]

    frontmatter_text = "\n".join(frontmatter_lines)
    body = "\n".join(body_lines).lstrip("\n")

    # Parse YAML safely
    # Use a custom resolver to treat timestamps as strings
    try:
        # Create a loader that doesn't auto-resolve timestamps
        loader = yaml.SafeLoader
        # Remove implicit timestamp resolver
        for ch in "0123456789":
            if len(loader.yaml_implicit_resolvers.get(ch, [])) > 0:
                loader.yaml_implicit_resolvers[ch] = [
                    (tag, regexp)
                    for tag, regexp in loader.yaml_implicit_resolvers[ch]
                    if tag != "tag:yaml.org,2002:timestamp"
                ]

        frontmatter = yaml.load(frontmatter_text, Loader=loader)

        # Handle empty frontmatter
        if frontmatter is None:
            frontmatter = {}

        # Validate it's a dict
        if not isinstance(frontmatter, dict):
            logger.warning(
                "Frontmatter is not a dict",
                extra={
                    "type": type(frontmatter).__name__,
                },
            )
            return ParsedContent({}, content)

        return ParsedContent(frontmatter, body)

    except yaml.YAMLError as e:
        logger.error(
            "YAML parse error in frontmatter",
            extra={
                "error": str(e),
                "frontmatter_length": len(frontmatter_text),
            },
        )
        msg = f"Invalid YAML in frontmatter: {e}"
        raise FrontmatterError(msg) from e


def serialize_frontmatter(frontmatter: dict[str, Any], body: str) -> str:
    """
    Serialize frontmatter and body back to markdown string.

    Args:
        frontmatter: Dictionary of frontmatter data
        body: Markdown body content

    Returns:
        Complete markdown string with frontmatter

    Raises:
        FrontmatterError: If frontmatter serialization fails
    """
    if not frontmatter:
        return body

    try:
        # Serialize YAML with proper formatting
        yaml_str = yaml.safe_dump(
            frontmatter,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

        # Remove trailing newline from YAML (yaml.dump adds one)
        yaml_str = yaml_str.rstrip("\n")

        return f"---\n{yaml_str}\n---\n\n{body}\n"

    except yaml.YAMLError as e:
        msg = f"Failed to serialize frontmatter: {e}"
        raise FrontmatterError(msg) from e


def update_frontmatter(
    content: str,
    updates: dict[str, Any],
    merge: bool = True,
) -> str:
    """
    Update frontmatter in markdown content.

    Args:
        content: Original markdown content
        updates: Dictionary of frontmatter updates
        merge: If True, merge with existing frontmatter; if False, replace

    Returns:
        Updated markdown content

    Raises:
        FrontmatterError: If parsing or serialization fails
    """
    parsed = parse_frontmatter(content)

    new_frontmatter = {**parsed.frontmatter, **updates} if merge else updates

    return serialize_frontmatter(new_frontmatter, parsed.body)


def strip_frontmatter(content: str) -> str:
    """
    Remove frontmatter from markdown content.

    Args:
        content: Markdown content with optional frontmatter

    Returns:
        Content body without frontmatter
    """
    parsed = parse_frontmatter(content)
    return parsed.body


def get_frontmatter(content: str) -> dict[str, Any]:
    """
    Extract frontmatter from markdown content.

    Args:
        content: Markdown content with optional frontmatter

    Returns:
        Frontmatter dictionary (empty dict if no frontmatter)
    """
    parsed = parse_frontmatter(content)
    return parsed.frontmatter


def parse_and_validate_capture(content: str) -> tuple[CaptureFrontmatter, str]:
    """
    Parse and validate capture file frontmatter.

    Args:
        content: Markdown content with frontmatter

    Returns:
        Tuple of (validated_frontmatter, body)

    Raises:
        FrontmatterError: If frontmatter is invalid or missing required fields
    """
    parsed = parse_frontmatter(content)

    if not parsed.frontmatter:
        msg = "Capture file must have frontmatter"
        raise FrontmatterError(msg)

    try:
        validated = CaptureFrontmatter(**parsed.frontmatter)
        return validated, parsed.body
    except ValidationError as e:
        logger.error(
            "Capture frontmatter validation failed",
            extra={
                "error": str(e),
                "frontmatter": parsed.frontmatter,
            },
        )
        msg = f"Capture frontmatter validation failed: {e}"
        raise FrontmatterError(msg) from e


def parse_and_validate_command(content: str) -> tuple[CommandFrontmatter, str]:
    """
    Parse and validate command file frontmatter.

    Args:
        content: Markdown content with command frontmatter

    Returns:
        Tuple of (validated_frontmatter, body)

    Raises:
        FrontmatterError: If frontmatter is invalid
    """
    parsed = parse_frontmatter(content)

    # Command frontmatter is optional, use defaults if missing
    try:
        validated = CommandFrontmatter(**parsed.frontmatter)
        return validated, parsed.body
    except ValidationError as e:
        logger.error(
            "Command frontmatter validation failed",
            extra={
                "error": str(e),
                "frontmatter": parsed.frontmatter,
            },
        )
        msg = f"Command frontmatter validation failed: {e}"
        raise FrontmatterError(msg) from e
