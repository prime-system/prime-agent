"""Tests for Claude session cursor pagination utilities."""

import base64
import json

import pytest

from app.utils.claude_session_pagination import (
    decode_session_cursor,
    encode_session_cursor,
    paginate_sessions,
)
from app.utils.pagination import PaginationError


def test_cursor_roundtrip() -> None:
    cursor = encode_session_cursor("2025-12-28T10:00:00+00:00", "session-1")
    assert decode_session_cursor(cursor) == ("2025-12-28T10:00:00+00:00", "session-1")


def test_cursor_roundtrip_with_none_last_activity() -> None:
    cursor = encode_session_cursor(None, "session-1")
    assert decode_session_cursor(cursor) == (None, "session-1")


def test_decode_invalid_base64() -> None:
    with pytest.raises(PaginationError):
        decode_session_cursor("not-base64")


def test_decode_invalid_json() -> None:
    raw = base64.urlsafe_b64encode(b"not-json").decode("utf-8").rstrip("=")
    with pytest.raises(PaginationError):
        decode_session_cursor(raw)


def test_decode_missing_fields() -> None:
    raw = (
        base64.urlsafe_b64encode(json.dumps({"session_id": "x"}).encode("utf-8"))
        .decode("utf-8")
        .rstrip("=")
    )
    with pytest.raises(PaginationError):
        decode_session_cursor(raw)


def test_paginate_sessions() -> None:
    sessions = [
        {"session_id": "session-2", "last_activity": "2025-12-28T12:00:00+00:00"},
        {"session_id": "session-1", "last_activity": "2025-12-28T11:00:00+00:00"},
        {"session_id": "session-0", "last_activity": "2025-12-28T10:00:00+00:00"},
    ]

    page1, cursor1 = paginate_sessions(sessions, limit=2, cursor=None)
    assert [item["session_id"] for item in page1] == ["session-2", "session-1"]
    assert cursor1 is not None

    page2, cursor2 = paginate_sessions(sessions, limit=2, cursor=cursor1)
    assert [item["session_id"] for item in page2] == ["session-0"]
    assert cursor2 is None
