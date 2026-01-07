"""Path validation utilities to prevent path traversal and symlink attacks."""

from __future__ import annotations

import re
from pathlib import Path


class PathValidationError(ValueError):
    """Raised when path validation fails."""


def validate_path_within_vault(
    path: str | Path,
    vault_root: Path,
    allow_symlinks: bool = False,
) -> Path:
    """Validate that path is within vault root and safe to use.

    Args:
        path: Path to validate (absolute or relative)
        vault_root: Vault root directory
        allow_symlinks: Whether to allow symlink paths

    Returns:
        Resolved absolute path within vault

    Raises:
        PathValidationError: If path is invalid or outside vault
    """
    # Convert to Path object and resolve vault_root first
    path = Path(path)
    vault_root_resolved = vault_root.resolve()

    # Check for null bytes before any processing
    if "\x00" in str(path):
        msg = "Path contains null bytes"
        raise PathValidationError(msg)

    # Check for obvious path traversal attempts
    path_str = str(path)
    if ".." in path_str:
        msg = "Path contains '..' which is not allowed"
        raise PathValidationError(msg)

    # If path is absolute, verify it's within vault before resolving
    if path.is_absolute():
        try:
            path.relative_to(vault_root_resolved)
        except ValueError:
            msg = f"Absolute path {path} is outside vault root {vault_root_resolved}"
            raise PathValidationError(msg)
        full_path = path
    else:
        full_path = vault_root_resolved / path

    # Check for symlinks BEFORE resolving (check should apply to any component)
    if not allow_symlinks:
        # Check if the path itself is a symlink
        if full_path.is_symlink():
            msg = f"Symlink not allowed: {full_path}"
            raise PathValidationError(msg)
        # Also check parent directories for symlinks
        try:
            for parent in full_path.parents:
                if parent.is_symlink():
                    msg = f"Symlink in path not allowed: {parent}"
                    raise PathValidationError(msg)
        except (OSError, RuntimeError):
            pass  # Some paths may not be accessible

    # Resolve path (follows symlinks and removes ..)
    try:
        resolved_path = full_path.resolve()
    except (OSError, RuntimeError) as e:
        msg = f"Cannot resolve path: {e}"
        raise PathValidationError(msg)

    # Check if resolved path is within vault
    try:
        resolved_path.relative_to(vault_root_resolved)
    except ValueError:
        msg = f"Path {resolved_path} is outside vault root {vault_root_resolved}"
        raise PathValidationError(msg)

    return resolved_path


def validate_folder_name(folder: str, vault_root: Path) -> Path:
    """Validate a folder name from configuration.

    Ensures the folder path:
    - Stays within vault root
    - Contains no path traversal sequences
    - Contains no absolute paths

    Args:
        folder: Folder name or relative path (e.g., ".prime/inbox" or "Daily")
        vault_root: Vault root directory

    Returns:
        Validated absolute path to folder

    Raises:
        PathValidationError: If folder is invalid
    """
    if not folder or not isinstance(folder, str):
        msg = "Folder name must be a non-empty string"
        raise PathValidationError(msg)

    # Check for null bytes
    if "\x00" in folder:
        msg = "Folder name contains null bytes"
        raise PathValidationError(msg)

    # Check for path traversal
    if ".." in folder:
        msg = "Folder name cannot contain '..'"
        raise PathValidationError(msg)

    # Check for absolute paths
    if folder.startswith(("/", "\\")):
        msg = "Folder name must be relative"
        raise PathValidationError(msg)

    # Check for multiple path separators in a row (e.g., "//", "\\\\")
    if "//" in folder or "\\\\" in folder:
        msg = "Folder name cannot contain consecutive separators"
        raise PathValidationError(msg)

    # Resolve vault root
    vault_root_resolved = vault_root.resolve()

    # Construct the folder path
    folder_path = vault_root_resolved / folder

    # Resolve the folder path
    try:
        resolved_folder = folder_path.resolve()
    except (OSError, RuntimeError) as e:
        msg = f"Cannot resolve folder path: {e}"
        raise PathValidationError(msg)

    # Final validation: ensure it stays within vault
    try:
        resolved_folder.relative_to(vault_root_resolved)
    except ValueError:
        msg = f"Folder {folder} resolves outside vault root"
        raise PathValidationError(msg)

    return resolved_folder


def sanitize_filename(filename: str, max_length: int = 255) -> str:
    """Sanitize filename to prevent path traversal and invalid characters.

    Removes:
    - Path separators (/ and \\)
    - Parent directory references (..)
    - Null bytes
    - Control characters
    - Leading/trailing spaces and dots

    Args:
        filename: Filename to sanitize
        max_length: Maximum length of sanitized filename

    Returns:
        Sanitized filename

    Raises:
        PathValidationError: If filename is empty after sanitization
    """
    if not filename or not isinstance(filename, str):
        msg = "Filename must be a non-empty string"
        raise PathValidationError(msg)

    # Remove null bytes and control characters first
    sanitized = "".join(c for c in filename if ord(c) >= 32 and c != "\x00")

    # Remove path separators
    sanitized = sanitized.replace("/", "_").replace("\\", "_")

    # Remove parent directory references (.. -> __)
    sanitized = sanitized.replace("..", "__")

    # Remove leading/trailing spaces and dots
    sanitized = sanitized.strip(". ")

    # Limit length
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]

    # Verify not empty after sanitization
    if not sanitized:
        msg = "Filename is empty after sanitization"
        raise PathValidationError(msg)

    return sanitized


def validate_session_id(session_id: str) -> str:
    """Validate session ID format.

    Accepts:
    - UUID format (e.g., "550e8400-e29b-41d4-a716-446655440000")
    - Alphanumeric with hyphens and underscores
    - No path traversal or special characters

    Args:
        session_id: Session ID to validate

    Returns:
        Validated session ID

    Raises:
        PathValidationError: If session ID is invalid
    """
    if not session_id or not isinstance(session_id, str):
        msg = "Session ID must be a non-empty string"
        raise PathValidationError(msg)

    # Check length
    if len(session_id) > 255:
        msg = "Session ID is too long"
        raise PathValidationError(msg)

    # Check for null bytes
    if "\x00" in session_id:
        msg = "Session ID contains null bytes"
        raise PathValidationError(msg)

    # Check for path traversal
    if ".." in session_id or "/" in session_id or "\\" in session_id:
        msg = "Session ID contains invalid path characters"
        raise PathValidationError(msg)

    # Allow UUID format or alphanumeric + hyphens/underscores
    # Pattern: UUID format (36 chars) or safe alphanumeric (up to 255 chars)
    uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    safe_id_pattern = r"^[a-zA-Z0-9._-]+$"

    if not (
        re.match(uuid_pattern, session_id, re.IGNORECASE) or re.match(safe_id_pattern, session_id)
    ):
        msg = "Session ID must be UUID format or contain only alphanumeric characters, hyphens, underscores, and dots"
        raise PathValidationError(msg)

    return session_id
