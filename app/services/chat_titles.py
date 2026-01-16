"""Chat title storage service for Claude sessions."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable

from pydantic import BaseModel, Field

from app.utils.path_validation import PathValidationError, validate_session_id

logger = logging.getLogger(__name__)

# Async lock for file operations (initialized in event loop)
_file_lock: asyncio.Lock | None = None


class ChatTitleEntry(BaseModel):
    """Stored chat title metadata."""

    title: str
    created_at: str
    source: Literal["generated", "fallback", "command"]


class ChatTitleStore(BaseModel):
    """Chat title storage model."""

    titles: dict[str, ChatTitleEntry] = Field(default_factory=dict)


def get_file_lock() -> asyncio.Lock:
    """Get the file lock, raising if not initialized."""
    if _file_lock is None:
        msg = "File lock not initialized. Call init_file_lock() first."
        raise RuntimeError(msg)
    return _file_lock


async def init_file_lock() -> asyncio.Lock:
    """Initialize the file lock in the running event loop."""
    global _file_lock
    _file_lock = asyncio.Lock()
    return _file_lock


class ChatTitleService:
    """Service for storing and retrieving chat titles."""

    def __init__(self, titles_file: Path) -> None:
        self.titles_file = titles_file

    def _load_titles(self) -> ChatTitleStore:
        if not self.titles_file.exists():
            return ChatTitleStore()

        try:
            with self.titles_file.open("r") as f:
                data = json.load(f)
            return ChatTitleStore(**data)
        except (json.JSONDecodeError, OSError, ValueError) as e:
            logger.error(
                "Failed to load chat titles",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "path": str(self.titles_file),
                },
            )
            return ChatTitleStore()

    def _save_titles(self, store: ChatTitleStore) -> None:
        self.titles_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file = self.titles_file.with_suffix(".json.tmp")

        try:
            with temp_file.open("w") as f:
                json.dump(store.model_dump(), f, indent=2)
                f.flush()

            temp_file.replace(self.titles_file)
            self.titles_file.chmod(0o600)
            logger.debug(
                "Chat titles saved",
                extra={"path": str(self.titles_file), "titles_count": len(store.titles)},
            )
        except OSError as e:
            logger.error(
                "Failed to save chat titles",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "path": str(self.titles_file),
                },
            )
            if temp_file.exists():
                temp_file.unlink()
            raise

    async def get_title(self, session_id: str) -> str | None:
        """Get a stored title for a session."""
        async with get_file_lock():
            store = self._load_titles()
            entry = store.titles.get(session_id)
            return entry.title if entry else None

    async def get_titles(self, session_ids: Iterable[str]) -> dict[str, str]:
        """Get titles for a collection of session IDs."""
        session_list: list[str] = []
        for session_id in session_ids:
            try:
                session_list.append(validate_session_id(session_id))
            except PathValidationError:
                logger.warning(
                    "Skipping invalid session ID for title lookup",
                    extra={"session_id": session_id},
                )

        if not session_list:
            return {}

        async with get_file_lock():
            store = self._load_titles()
            return {
                session_id: entry.title
                for session_id in session_list
                if (entry := store.titles.get(session_id))
            }

    async def set_title(
        self,
        session_id: str,
        title: str,
        created_at: str,
        *,
        source: Literal["generated", "fallback", "command"],
    ) -> None:
        """Persist a title for a session."""
        validated_id = validate_session_id(session_id)
        cleaned_title = title.strip()
        if not cleaned_title:
            logger.warning(
                "Skipping empty chat title",
                extra={"session_id": validated_id},
            )
            return

        async with get_file_lock():
            store = self._load_titles()
            store.titles[validated_id] = ChatTitleEntry(
                title=cleaned_title,
                created_at=created_at,
                source=source,
            )
            self._save_titles(store)

        logger.info(
            "Chat title stored",
            extra={"session_id": validated_id, "source": source},
        )

    async def title_exists(self, session_id: str) -> bool:
        """Check if a title exists for a session."""
        async with get_file_lock():
            store = self._load_titles()
            return session_id in store.titles
