import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from app.models.capture import CaptureRequest
from app.utils.frontmatter import parse_frontmatter

logger = logging.getLogger(__name__)


class InboxService:
    """Handles inbox file operations for per-capture mode."""

    def generate_dump_id(self, captured_at: datetime, source: str) -> str:
        """
        Generate unique dump ID.

        Format: {ISO8601 timestamp}-{source}
        Example: 2025-12-21T14:30:00Z-iphone
        """
        timestamp = captured_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        return f"{timestamp}-{source}"

    def _build_metadata(self, request: CaptureRequest, dump_id: str) -> dict[str, object]:
        """Build metadata dictionary from capture request."""
        context_dict: dict[str, object] = {"app": request.context.app.value}

        if request.context.location:
            context_dict["location"] = {
                "latitude": request.context.location.latitude,
                "longitude": request.context.location.longitude,
            }

        return {
            "id": dump_id,
            "captured_at": request.captured_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": request.source.value,
            "input": request.input.value,
            "context": context_dict,
        }

    def format_capture_file(self, request: CaptureRequest, dump_id: str) -> str:
        """
        Format a capture request as a standalone markdown file with frontmatter.

        Output format:
        ```
        ---
        id: 2025-12-21T14:30:00Z-iphone
        captured_at: 2025-12-21T14:30:00Z
        source: iphone
        input: voice
        context:
          app: shortcuts
        ---

        Raw text content here...
        ```
        """
        metadata = self._build_metadata(request, dump_id)
        yaml_content = yaml.dump(metadata, default_flow_style=False, sort_keys=False)

        return f"---\n{yaml_content}---\n\n{request.text}\n"

    def write_capture(self, file_path: Path, content: str) -> None:
        """
        Write a capture to its own file.

        Creates the file and parent directories if they don't exist.
        """
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

    def get_unprocessed_dumps(self, vault_path: Path, inbox_folder: str) -> list[dict[str, Any]]:
        """
        Scan configured inbox folder for files without processed: true.

        Uses grep for performance - much faster than reading all files in Python.

        Args:
            vault_path: Path to vault directory
            inbox_folder: Configured inbox folder name (from .prime.yaml)

        Returns:
            List of dicts with dump metadata and preview
        """
        inbox_dir = vault_path / inbox_folder
        if not inbox_dir.exists():
            return []

        unprocessed: list[dict[str, Any]] = []

        try:
            # Use grep to find all .md files that DON'T contain "processed: true"
            # -L lists files that don't match
            # -r recursive search
            # --include only .md files
            result = subprocess.run(
                [
                    "grep",
                    "-L",  # List files that don't match
                    "-r",  # Recursive
                    "--include=*.md",  # Only .md files
                    "processed: true",  # Pattern to NOT match
                    str(inbox_dir),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            # grep -L returns 0 if files found, 1 if no files found, 2 on error
            if result.returncode == 2:
                # Error occurred, fall back to Python implementation
                return self._get_unprocessed_dumps_python(vault_path, inbox_folder)

            if result.returncode == 1:
                # No unprocessed files found
                return []

            # Parse each file found by grep
            for file_path_str in result.stdout.strip().split("\n"):
                if not file_path_str:
                    continue

                md_file = Path(file_path_str)
                try:
                    content = md_file.read_text(encoding="utf-8")

                    # Parse YAML frontmatter using robust parser
                    parsed = parse_frontmatter(content)
                    metadata = parsed.frontmatter
                    body = parsed.body

                    # Skip if no metadata or missing required fields
                    if not metadata or not metadata.get("id"):
                        continue

                    preview = body.strip()[:100]

                    # Build response dict
                    unprocessed.append(
                        {
                            "id": metadata.get("id", "unknown"),
                            "file": str(md_file.relative_to(vault_path)),
                            "captured_at": metadata.get("captured_at", "unknown"),
                            "source": metadata.get("source", "unknown"),
                            "input": metadata.get("input", "unknown"),
                            "preview": preview,
                        }
                    )

                except Exception as e:
                    # Log and skip files that can't be parsed
                    logger.debug(
                        "Failed to parse capture file",
                        extra={
                            "file": str(md_file),
                            "error": str(e),
                        },
                    )
                    continue

        except FileNotFoundError:
            # grep not available, fall back to Python implementation
            return self._get_unprocessed_dumps_python(vault_path, inbox_folder)

        # Sort by captured_at (oldest first)
        unprocessed.sort(key=lambda x: x["captured_at"])

        return unprocessed

    def _get_unprocessed_dumps_python(
        self, vault_path: Path, inbox_folder: str
    ) -> list[dict[str, Any]]:
        """
        Fallback Python implementation for scanning unprocessed dumps.

        Used when grep is not available or fails.

        Args:
            vault_path: Path to vault directory
            inbox_folder: Configured inbox folder name

        Returns:
            List of dicts with dump metadata and preview
        """
        inbox_dir = vault_path / inbox_folder
        if not inbox_dir.exists():
            return []

        unprocessed: list[dict[str, Any]] = []

        # Recursively find all .md files in inbox
        for md_file in inbox_dir.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")

                # Parse YAML frontmatter using robust parser
                parsed = parse_frontmatter(content)
                metadata = parsed.frontmatter
                body = parsed.body

                # Skip if already processed or no metadata
                if not metadata or not metadata.get("id"):
                    continue

                if metadata.get("processed") is True:
                    continue

                preview = body.strip()[:100]

                # Build response dict
                unprocessed.append(
                    {
                        "id": metadata.get("id", "unknown"),
                        "file": str(md_file.relative_to(vault_path)),
                        "captured_at": metadata.get("captured_at", "unknown"),
                        "source": metadata.get("source", "unknown"),
                        "input": metadata.get("input", "unknown"),
                        "preview": preview,
                    }
                )

            except Exception as e:
                # Log and skip files that can't be parsed
                logger.debug(
                    "Failed to parse capture file",
                    extra={
                        "file": str(md_file),
                        "error": str(e),
                    },
                )
                continue

        # Sort by captured_at (oldest first)
        unprocessed.sort(key=lambda x: x["captured_at"])

        return unprocessed
