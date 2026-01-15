"""Unit tests for chat title storage service."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.chat_titles import ChatTitleService, init_file_lock
from app.utils.path_validation import PathValidationError


@pytest.fixture(autouse=True)
async def setup_file_lock() -> None:
    """Initialize file lock before each async test."""
    await init_file_lock()


@pytest.mark.asyncio
async def test_get_title_returns_none_when_missing(tmp_path: Path) -> None:
    titles_file = tmp_path / "chat" / "titles.json"
    service = ChatTitleService(titles_file)

    title = await service.get_title("session-1")

    assert title is None


@pytest.mark.asyncio
async def test_set_and_get_title_persists(tmp_path: Path) -> None:
    titles_file = tmp_path / "chat" / "titles.json"
    service = ChatTitleService(titles_file)

    await service.set_title(
        "session-1",
        "My Title",
        "2026-01-01T00:00:00Z",
        source="generated",
    )

    assert await service.get_title("session-1") == "My Title"
    assert titles_file.exists()
    assert titles_file.stat().st_mode & 0o777 == 0o600

    data = json.loads(titles_file.read_text())
    assert data["titles"]["session-1"]["title"] == "My Title"
    assert data["titles"]["session-1"]["source"] == "generated"
    assert not titles_file.with_suffix(".json.tmp").exists()


@pytest.mark.asyncio
async def test_get_titles_filters_invalid_ids(tmp_path: Path) -> None:
    titles_file = tmp_path / "chat" / "titles.json"
    service = ChatTitleService(titles_file)

    await service.set_title(
        "session-1",
        "First Title",
        "2026-01-01T00:00:00Z",
        source="generated",
    )
    await service.set_title(
        "session-2",
        "Second Title",
        "2026-01-02T00:00:00Z",
        source="fallback",
    )

    titles = await service.get_titles(["session-1", "bad/../id", "session-2"])

    assert titles == {"session-1": "First Title", "session-2": "Second Title"}


@pytest.mark.asyncio
async def test_set_title_rejects_invalid_session_id(tmp_path: Path) -> None:
    titles_file = tmp_path / "chat" / "titles.json"
    service = ChatTitleService(titles_file)

    with pytest.raises(PathValidationError):
        await service.set_title(
            "bad/../id",
            "Title",
            "2026-01-01T00:00:00Z",
            source="generated",
        )


@pytest.mark.asyncio
async def test_title_exists(tmp_path: Path) -> None:
    titles_file = tmp_path / "chat" / "titles.json"
    service = ChatTitleService(titles_file)

    await service.set_title(
        "session-1",
        "My Title",
        "2026-01-01T00:00:00Z",
        source="generated",
    )

    assert await service.title_exists("session-1") is True
    assert await service.title_exists("session-2") is False
