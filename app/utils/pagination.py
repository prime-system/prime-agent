"""Pagination utilities for cursor-based listing endpoints."""

from __future__ import annotations

import base64
from typing import TypeVar

T = TypeVar("T")


class PaginationError(ValueError):
    """Raised when a pagination cursor is invalid."""


def encode_cursor(offset: int) -> str:
    """Encode an integer offset into an opaque cursor string."""
    if offset < 0:
        msg = "Offset must be non-negative"
        raise PaginationError(msg)
    raw = f"offset:{offset}".encode()
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def decode_cursor(cursor: str) -> int:
    """Decode an opaque cursor string into an integer offset."""
    if not cursor:
        msg = "Cursor cannot be empty"
        raise PaginationError(msg)

    padding = "=" * (-len(cursor) % 4)
    try:
        decoded = base64.urlsafe_b64decode((cursor + padding).encode("utf-8")).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        msg = "Cursor is not valid base64"
        raise PaginationError(msg) from exc

    if not decoded.startswith("offset:"):
        msg = "Cursor format is invalid"
        raise PaginationError(msg)

    try:
        offset = int(decoded.split(":", 1)[1])
    except ValueError as exc:
        msg = "Cursor offset is invalid"
        raise PaginationError(msg) from exc

    if offset < 0:
        msg = "Cursor offset must be non-negative"
        raise PaginationError(msg)

    return offset


def paginate_items(
    items: list[T],
    limit: int,
    cursor: str | None,
) -> tuple[list[T], str | None]:
    """Paginate a list of items with an opaque cursor."""
    offset = 0
    if cursor is not None:
        offset = decode_cursor(cursor)

    if offset > len(items):
        msg = "Cursor offset out of range"
        raise PaginationError(msg)

    end = offset + limit
    next_cursor = encode_cursor(end) if end < len(items) else None
    return items[offset:end], next_cursor
