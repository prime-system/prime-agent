from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
from datetime import UTC, datetime
from os import stat_result  # noqa: TC003
from typing import TYPE_CHECKING, Literal

from app.exceptions import ValidationError, VaultError
from app.models.vault_browser import FileItem, FileMetadata, FolderItem, Item
from app.utils.path_validation import PathValidationError, validate_path_within_vault

if TYPE_CHECKING:
    from pathlib import Path

    from app.services.vault import VaultService

logger = logging.getLogger(__name__)

# Hardcoded configuration (no Settings needed)
MAX_PAGE_SIZE = 1000
DEFAULT_PAGE_SIZE = 200
FOLLOW_SYMLINKS = False  # Security policy - never configurable


class VaultBrowserService:
    """Service for browsing vault files and folders."""

    def __init__(self, vault_service: VaultService) -> None:
        """
        Initialize vault browser service.

        Args:
            vault_service: VaultService instance
        """
        self.vault_service = vault_service

    async def list_folder(
        self,
        api_path: str,
        show_hidden: bool = False,
        include_types: set[Literal["file", "folder"]] | None = None,
    ) -> list[Item]:
        """
        List contents of a folder.

        Args:
            api_path: Canonical API path (e.g., "/Daily")
            show_hidden: Include dotfiles (client choice per request)
            include_types: Filter by item types (None = all)

        Returns:
            List of FileItem and FolderItem objects

        Raises:
            ValidationError: Path invalid or unsafe
            VaultError: Symlink policy violation
            FileNotFoundError: Folder doesn't exist
            NotADirectoryError: Path is a file, not folder
        """
        fs_path, normalized_path = self._resolve_api_path(api_path)

        if not fs_path.exists():
            msg = f"Folder not found: {normalized_path}"
            raise FileNotFoundError(msg)

        if not fs_path.is_dir():
            msg = f"Path is a file: {normalized_path}"
            raise NotADirectoryError(msg)

        return await asyncio.to_thread(
            self._list_directory_sync,
            fs_path,
            normalized_path,
            show_hidden,
            include_types,
        )

    async def get_file_metadata(self, api_path: str) -> FileMetadata:
        """
        Get metadata for a file.

        Args:
            api_path: Canonical API path (e.g., "/Notes/idea.md")

        Returns:
            FileMetadata for the file

        Raises:
            ValidationError: Path invalid or unsafe
            VaultError: Symlink policy violation
            FileNotFoundError: File doesn't exist
            IsADirectoryError: Path is a directory, not file
        """
        fs_path, normalized_path = self._resolve_api_path(api_path)
        return await asyncio.to_thread(
            self._get_file_metadata_sync,
            fs_path,
            normalized_path,
        )

    async def get_file_info(self, api_path: str) -> tuple[Path, FileMetadata]:
        """
        Get file path and metadata together for content reads.

        Args:
            api_path: Canonical API path (e.g., "/Notes/idea.md")

        Returns:
            Tuple of (filesystem path, FileMetadata)
        """
        fs_path, normalized_path = self._resolve_api_path(api_path)
        metadata = await asyncio.to_thread(
            self._get_file_metadata_sync,
            fs_path,
            normalized_path,
        )
        return fs_path, metadata

    async def read_file_range(self, fs_path: Path, start: int, length: int) -> bytes:
        """Read a byte range from a file."""
        return await asyncio.to_thread(self._read_file_range_sync, fs_path, start, length)

    def generate_file_etag(self, size: int, mtime_ns: int) -> str:
        """Generate a strong ETag for a file."""
        raw = f"{size}:{mtime_ns}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f'"{digest}"'

    def generate_folder_etag(
        self,
        api_path: str,
        items: list[Item],
        show_hidden: bool,
    ) -> str:
        """Generate a strong ETag for a folder listing."""
        normalized_path = self._normalize_api_path(api_path)
        payload = [f"path={normalized_path}", f"hidden={show_hidden}"]

        parts: list[str] = []
        for item in items:
            if isinstance(item, FileItem):
                parts.append(
                    f"file:{item.path}:{item.size}:{item.modified_at.isoformat()}:{item.etag}"
                )
            else:
                child_count = item.child_count if item.child_count is not None else ""
                parts.append(f"folder:{item.path}:{child_count}:{item.modified_at.isoformat()}")

        payload.extend(sorted(parts))

        digest = hashlib.sha256("|".join(payload).encode("utf-8")).hexdigest()
        return f'"{digest}"'

    def normalize_api_path(self, api_path: str) -> str:
        """Expose normalized API paths for response payloads."""
        return self._normalize_api_path(api_path)

    def _normalize_api_path(self, api_path: str) -> str:
        """Normalize API paths to a canonical form."""
        if not isinstance(api_path, str):
            msg = "Path must be a string"
            raise ValidationError(msg, context={"path": api_path})

        cleaned = api_path.strip()
        if not cleaned:
            msg = "Path cannot be empty"
            raise ValidationError(msg, context={"path": api_path})

        if "\x00" in cleaned:
            msg = "Path contains null bytes"
            raise ValidationError(msg, context={"path": api_path})

        if "\\" in cleaned:
            msg = "Path cannot contain backslashes"
            raise ValidationError(msg, context={"path": api_path})

        if not cleaned.startswith("/"):
            msg = "Path must start with '/'"
            raise ValidationError(msg, context={"path": api_path})

        cleaned = cleaned.rstrip("/")
        if cleaned == "":
            cleaned = "/"

        return cleaned

    def _resolve_api_path(self, api_path: str) -> tuple[Path, str]:
        """Validate and resolve an API path to a filesystem path."""
        normalized_path = self._normalize_api_path(api_path)
        if normalized_path == "/":
            return self.vault_service.vault_path.resolve(), normalized_path

        relative_path = normalized_path.lstrip("/")
        try:
            resolved = validate_path_within_vault(
                relative_path,
                self.vault_service.vault_path,
                allow_symlinks=FOLLOW_SYMLINKS,
            )
        except PathValidationError as exc:
            message = str(exc)
            if "Symlink" in message:
                msg = "Symlink access is not allowed"
                raise VaultError(
                    msg,
                    context={
                        "path": normalized_path,
                        "reason": "symlink_not_allowed",
                    },
                ) from exc
            msg = "Invalid path"
            raise ValidationError(
                msg,
                context={
                    "path": normalized_path,
                    "reason": "invalid_path",
                    "detail": message,
                },
            ) from exc

        return resolved, normalized_path

    def _list_directory_sync(
        self,
        fs_path: Path,
        api_path: str,
        show_hidden: bool,
        include_types: set[Literal["file", "folder"]] | None,
    ) -> list[Item]:
        """Synchronous directory listing (runs in thread)."""
        items: list[Item] = []

        for entry in fs_path.iterdir():
            if not show_hidden and entry.name.startswith("."):
                continue

            if entry.is_symlink():
                continue

            child_api_path = self._join_api_path(api_path, entry.name)

            try:
                stat = entry.stat()
            except OSError:
                logger.debug(
                    "Skipping unreadable vault entry",
                    extra={
                        "path": str(entry),
                        "api_path": child_api_path,
                    },
                )
                continue

            if entry.is_dir():
                if include_types and "folder" not in include_types:
                    continue

                items.append(
                    FolderItem.model_validate(
                        {
                            "name": entry.name,
                            "path": child_api_path,
                            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                            "child_count": None,
                        }
                    )
                )
                continue

            if entry.is_file():
                if include_types and "file" not in include_types:
                    continue

                items.append(
                    FileItem.model_validate(
                        {
                            "name": entry.name,
                            "path": child_api_path,
                            "size": stat.st_size,
                            "mime_type": self._detect_mime_type(entry),
                            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                            "etag": self._generate_file_etag(stat),
                        }
                    )
                )

        return items

    def _get_file_metadata_sync(self, fs_path: Path, api_path: str) -> FileMetadata:
        """Synchronous file metadata lookup (runs in thread)."""
        if not fs_path.exists():
            msg = f"File not found: {api_path}"
            raise FileNotFoundError(msg)

        if not fs_path.is_file():
            msg = f"Path is a folder: {api_path}"
            raise IsADirectoryError(msg)

        stat = fs_path.stat()
        return FileMetadata.model_validate(
            {
                "name": fs_path.name,
                "path": api_path,
                "size": stat.st_size,
                "mime_type": self._detect_mime_type(fs_path),
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                "etag": self._generate_file_etag(stat),
            }
        )

    def _read_file_range_sync(self, fs_path: Path, start: int, length: int) -> bytes:
        """Read a byte range from a file (sync)."""
        with fs_path.open("rb") as handle:
            handle.seek(start)
            return handle.read(length)

    def _detect_mime_type(self, path: Path) -> str | None:
        """Detect MIME type from filename."""
        mime_type, _ = mimetypes.guess_type(str(path))
        return mime_type

    def _generate_file_etag(self, stat_result: stat_result) -> str:
        """Generate file ETag from stat metadata."""
        mtime_ns = getattr(stat_result, "st_mtime_ns", None)
        if mtime_ns is None:
            mtime_ns = int(stat_result.st_mtime * 1_000_000_000)
        size = stat_result.st_size
        return self.generate_file_etag(size, int(mtime_ns))

    def _join_api_path(self, base: str, name: str) -> str:
        """Join base API path and entry name."""
        if base == "/":
            return f"/{name}"
        return f"{base}/{name}"
