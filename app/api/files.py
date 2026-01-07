"""File content API for previewing vault files."""

import logging
import mimetypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.dependencies import get_vault_service, verify_token
from app.services.vault import VaultService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/files", dependencies=[Depends(verify_token)])


class FileContentResponse(BaseModel):
    """File content response model."""

    path: str
    content: str
    size_bytes: int
    lines: int
    language: str | None
    modified_at: datetime | None


def validate_safe_path(path_str: str, vault_path: Path) -> Path:
    """
    Validate and resolve a path to ensure it's within the vault directory.

    Args:
        path_str: Relative path string from request
        vault_path: Absolute path to vault root

    Returns:
        Resolved absolute path

    Raises:
        HTTPException: If path is invalid or tries to escape vault
    """
    # Remove leading/trailing whitespace
    path_str = path_str.strip()

    # Reject empty paths
    if not path_str:
        raise HTTPException(status_code=400, detail="Path cannot be empty")

    # Handle absolute paths: if it's an absolute path, try to make it relative to vault
    if path_str.startswith("/"):
        try:
            # Try to make the absolute path relative to the vault
            abs_path = Path(path_str)
            vault_resolved = vault_path.resolve()
            path_str = str(abs_path.relative_to(vault_resolved))
        except ValueError:
            # Path is absolute but not under vault - reject it
            raise HTTPException(
                status_code=403,
                detail=f"Absolute path must be within vault directory: {vault_path}",
            ) from None

    # Remove leading/trailing slashes
    path_str = path_str.strip("/")

    # Reject paths with .. components (path traversal)
    if ".." in Path(path_str).parts:
        raise HTTPException(status_code=400, detail="Path traversal (..) not allowed")

    # Resolve the full path
    full_path = (vault_path / path_str).resolve()

    # Ensure the resolved path is still within vault
    try:
        full_path.relative_to(vault_path.resolve())
    except ValueError as err:
        raise HTTPException(status_code=403, detail="Access denied: path outside vault") from err

    return full_path


def detect_language(file_path: Path) -> str | None:
    """
    Detect programming language from file extension.

    Args:
        file_path: Path to the file

    Returns:
        Language identifier (e.g., 'python', 'javascript', 'markdown')
    """
    ext = file_path.suffix.lower()
    language_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".jsx": "javascript",
        ".tsx": "typescript",
        ".md": "markdown",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".sh": "bash",
        ".bash": "bash",
        ".zsh": "zsh",
        ".swift": "swift",
        ".go": "go",
        ".rs": "rust",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c",
        ".hpp": "cpp",
        ".html": "html",
        ".css": "css",
        ".xml": "xml",
        ".sql": "sql",
    }
    return language_map.get(ext)


def is_binary_file(file_path: Path) -> bool:
    """
    Check if a file is binary.

    Args:
        file_path: Path to the file

    Returns:
        True if file appears to be binary
    """
    # Check by MIME type first
    mime_type, _ = mimetypes.guess_type(str(file_path))
    if mime_type and not mime_type.startswith("text/"):
        return True

    # Check by extension
    binary_extensions = {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".pdf",
        ".zip",
        ".tar",
        ".gz",
        ".exe",
        ".bin",
        ".so",
        ".dylib",
        ".dll",
    }
    return file_path.suffix.lower() in binary_extensions


@router.get("/content")
async def get_file_content(
    path: Annotated[str, Query(description="Relative path from vault root")],
    lines: Annotated[
        int | None, Query(description="Max lines to return (default: all)", ge=1)
    ] = None,
    offset: Annotated[int | None, Query(description="Line offset for pagination", ge=0)] = 0,
    vault_service: VaultService = Depends(get_vault_service),
) -> FileContentResponse:
    """
    Get file content from vault.

    Returns file content with metadata for preview in the app.
    Only serves files within the vault directory.
    """
    vault_path = vault_service.vault_path

    # Validate and resolve path
    full_path = validate_safe_path(path, vault_path)

    # Check if file exists
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    # Check if it's a file (not a directory)
    if not full_path.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")

    # Check if binary
    if is_binary_file(full_path):
        raise HTTPException(status_code=400, detail="Binary file preview not supported")

    # Read file content
    try:
        content = full_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as err:
        raise HTTPException(
            status_code=400, detail="File encoding not supported (non-UTF-8)"
        ) from err
    except OSError as err:
        logger.error("Failed to read file %s: %s", full_path, err)
        raise HTTPException(status_code=500, detail="Failed to read file") from err

    # Split into lines for pagination
    all_lines = content.splitlines(keepends=True)
    total_lines = len(all_lines)

    # Apply offset and line limit
    start = offset or 0
    if start >= total_lines:
        # Offset beyond file length
        selected_lines = []
    else:
        end = start + lines if lines else total_lines
        selected_lines = all_lines[start:end]

    content_to_return = "".join(selected_lines)

    # Get file stats
    stat = full_path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)

    # Detect language
    language = detect_language(full_path)

    return FileContentResponse(
        path=path,
        content=content_to_return,
        size_bytes=stat.st_size,
        lines=total_lines,
        language=language,
        modified_at=modified_at,
    )
