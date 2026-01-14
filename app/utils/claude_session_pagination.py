"""Cursor-based pagination utilities for Claude session listings."""

from __future__ import annotations

import base64
import json
from typing import Any

from app.utils.pagination import PaginationError


def encode_session_cursor(last_activity: str | None, session_id: str) -> str:
    """Encode session cursor data into an opaque base64url string."""
    payload = {"last_activity": last_activity, "session_id": session_id}
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def decode_session_cursor(cursor: str) -> tuple[str | None, str]:
    """Decode an opaque session cursor into last_activity and session_id."""
    if not cursor:
        msg = "Cursor cannot be empty"
        raise PaginationError(msg)

    padding = "=" * (-len(cursor) % 4)
    try:
        decoded = base64.urlsafe_b64decode((cursor + padding).encode("utf-8")).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        msg = "Cursor is not valid base64"
        raise PaginationError(msg) from exc

    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError as exc:
        msg = "Cursor is not valid JSON"
        raise PaginationError(msg) from exc

    if not isinstance(payload, dict):
        msg = "Cursor payload must be an object"
        raise PaginationError(msg)

    if "last_activity" not in payload or "session_id" not in payload:
        msg = "Cursor payload missing required fields"
        raise PaginationError(msg)

    last_activity = payload["last_activity"]
    session_id = payload["session_id"]

    if last_activity is not None and not isinstance(last_activity, str):
        msg = "Cursor last_activity must be a string or null"
        raise PaginationError(msg)

    if not isinstance(session_id, str):
        msg = "Cursor session_id must be a string"
        raise PaginationError(msg)

    return last_activity, session_id


def paginate_sessions(
    sessions: list[dict[str, Any]],
    limit: int,
    cursor: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Paginate sessions using a cursor derived from last_activity and session_id.

    The input list must already be sorted by last_activity (desc) then session_id (desc).
    """
    start_index = 0
    if cursor is not None:
        cursor_last_activity, cursor_session_id = decode_session_cursor(cursor)
        cursor_key = _session_sort_key(cursor_last_activity, cursor_session_id)
        start_index = _find_start_index(sessions, cursor_key)

    end_index = start_index + limit
    page = list(sessions[start_index:end_index])

    if not page or end_index >= len(sessions):
        return page, None

    last_activity, session_id = _extract_cursor_fields(page[-1])
    next_cursor = encode_session_cursor(last_activity, session_id)
    return page, next_cursor


def _find_start_index(
    sessions: list[dict[str, Any]],
    cursor_key: tuple[str, str],
) -> int:
    for index, session in enumerate(sessions):
        session_key = _session_sort_key(*_extract_cursor_fields(session))
        if session_key < cursor_key:
            return index
    return len(sessions)


def _extract_cursor_fields(session: dict[str, Any]) -> tuple[str | None, str]:
    session_id = session.get("session_id")
    if not isinstance(session_id, str):
        msg = "Session is missing a valid session_id"
        raise ValueError(msg)

    last_activity = session.get("last_activity")
    if last_activity is not None and not isinstance(last_activity, str):
        msg = "Session last_activity must be a string or null"
        raise ValueError(msg)

    return last_activity, session_id


def _session_sort_key(last_activity: str | None, session_id: str) -> tuple[str, str]:
    return (last_activity or "", session_id)
