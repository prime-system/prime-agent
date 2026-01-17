from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from app.exceptions import SearchError, ValidationError
from app.models.vault_search import SearchMatch, SearchRequest, SearchResponse
from app.utils.path_validation import PathValidationError, validate_path_within_vault

if TYPE_CHECKING:
    from collections.abc import Iterable

    from app.services.vault import VaultService

logger = logging.getLogger(__name__)

MIN_MAX_RESULTS = 1
MAX_MAX_RESULTS = 1000
SEARCH_TIMEOUT_SECONDS = 10
FOLLOW_SYMLINKS = False
EXCLUDED_GLOBS = (".git",)


def build_rg_args(
    request: SearchRequest,
    show_hidden: bool,
    search_path: str,
) -> list[str]:
    """Build ripgrep arguments for the search request."""
    args = [
        "rg",
        "--json",
        "--line-number",
        "--column",
        "--no-heading",
        "--color",
        "never",
    ]

    if not request.regex:
        args.append("--fixed-strings")

    if not request.case_sensitive:
        args.append("--smart-case")

    if request.context_lines > 0:
        args.extend(["--context", str(request.context_lines)])

    if show_hidden:
        args.append("--hidden")

    for glob in EXCLUDED_GLOBS:
        args.extend(["--glob", f"!{glob}/**"])

    if request.globs:
        for glob in request.globs:
            args.extend(["--glob", glob])

    args.append("--")
    args.append(request.query)
    args.append(search_path)

    return args


def parse_rg_output(
    output: str,
    vault_root: Path,
    context_lines: int,
    max_matches: int | None = None,
) -> list[SearchMatch]:
    """Parse ripgrep JSON output into structured matches."""
    lines_by_path: dict[str, dict[int, str]] = {}
    matches: list[tuple[str, int, int, str]] = []

    for raw_line in output.splitlines():
        if not raw_line:
            continue

        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            msg = "Failed to parse ripgrep output"
            raise SearchError(
                msg,
                context={
                    "reason": "invalid_json",
                },
            ) from exc

        event_type = payload.get("type")
        if event_type not in {"match", "context"}:
            continue

        data = payload.get("data", {})
        path_text = data.get("path", {}).get("text")
        line_number = data.get("line_number")
        line_text = data.get("lines", {}).get("text")

        if not path_text or line_number is None or line_text is None:
            continue

        cleaned_text = line_text.rstrip("\r\n")
        lines_by_path.setdefault(path_text, {})[int(line_number)] = cleaned_text

        if event_type != "match":
            continue

        submatches = data.get("submatches") or []
        if not submatches:
            if max_matches is None or len(matches) < max_matches:
                matches.append((path_text, int(line_number), 1, cleaned_text))
            continue

        for submatch in submatches:
            if max_matches is not None and len(matches) >= max_matches:
                break
            start = submatch.get("start")
            column = int(start) + 1 if isinstance(start, int) else 1
            matches.append((path_text, int(line_number), column, cleaned_text))

    vault_root_resolved = vault_root.resolve()
    results: list[SearchMatch] = []

    for path_text, line_number, column, text in matches:
        path = Path(path_text)
        absolute_path = path if path.is_absolute() else vault_root_resolved / path

        try:
            relative_path = absolute_path.relative_to(vault_root_resolved)
            normalized_path = relative_path.as_posix()
        except ValueError:
            normalized_path = path.as_posix()

        if context_lines > 0:
            line_map = lines_by_path.get(path_text, {})
            context_before = [
                line_map[line_number - offset]
                for offset in range(context_lines, 0, -1)
                if (line_number - offset) in line_map
            ]
            context_after = [
                line_map[line_number + offset]
                for offset in range(1, context_lines + 1)
                if (line_number + offset) in line_map
            ]
        else:
            context_before = []
            context_after = []

        results.append(
            SearchMatch(
                path=normalized_path,
                line=line_number,
                column=column,
                text=text,
                context_before=context_before,
                context_after=context_after,
            )
        )

    return results


class VaultSearchService:
    """Service for searching vault contents via ripgrep."""

    def __init__(self, vault_service: VaultService) -> None:
        self.vault_service = vault_service

    async def search(self, request: SearchRequest, show_hidden: bool = False) -> SearchResponse:
        """Search the vault using ripgrep and return structured results."""
        self._validate_request(request)

        search_root = self._resolve_search_root(request.folder)
        search_path = self._relative_search_path(search_root)
        args = build_rg_args(request, show_hidden, search_path)

        start_time = time.monotonic()
        stdout, stderr, exit_code = await self._run_rg(args)
        duration_ms = int((time.monotonic() - start_time) * 1000)

        if exit_code == 1:
            results: list[SearchMatch] = []
        elif exit_code == 0:
            results = parse_rg_output(
                stdout,
                self.vault_service.vault_path,
                request.context_lines,
                max_matches=request.max_results + 1,
            )
        elif exit_code == 2:
            message = stderr.strip() or "Invalid search pattern"
            raise ValidationError(
                message,
                context={
                    "reason": "invalid_regex",
                },
            )
        else:
            msg = "Search command failed"
            raise SearchError(
                msg,
                context={
                    "exit_code": exit_code,
                },
            )

        content_truncated = len(results) > request.max_results
        results = results[: request.max_results]

        filename_matches, filename_truncated = await asyncio.to_thread(
            self._search_filenames,
            request,
            search_root=search_root,
            show_hidden=show_hidden,
            max_results=request.max_results,
        )
        filename_matches = filename_matches[: request.max_results]

        combined_results = list(filename_matches)
        remaining_slots = request.max_results - len(combined_results)
        if remaining_slots > 0:
            combined_results.extend(results[:remaining_slots])

        truncated = (
            content_truncated
            or filename_truncated
            or (len(filename_matches) + len(results)) > request.max_results
        )

        logger.info(
            "Vault search completed",
            extra={
                "query_length": len(request.query),
                "regex": request.regex,
                "case_sensitive": request.case_sensitive,
                "folder": request.folder,
                "globs_count": len(request.globs or []),
                "show_hidden": show_hidden,
                "max_results": request.max_results,
                "context_lines": request.context_lines,
                "result_count": len(combined_results),
                "filename_match_count": len(filename_matches),
                "truncated": truncated,
                "duration_ms": duration_ms,
            },
        )

        return SearchResponse(
            query=request.query,
            results=combined_results,
            total_matches=len(combined_results),
            truncated=truncated,
            duration_ms=duration_ms,
        )

    def _validate_request(self, request: SearchRequest) -> None:
        if not isinstance(request.query, str) or not request.query.strip():
            msg = "Query must be non-empty"
            raise ValidationError(msg, context={"field": "query"})

        if request.max_results < MIN_MAX_RESULTS or request.max_results > MAX_MAX_RESULTS:
            msg = "max_results out of range"
            raise ValidationError(
                msg,
                context={
                    "field": "max_results",
                    "min": MIN_MAX_RESULTS,
                    "max": MAX_MAX_RESULTS,
                },
            )

        if request.context_lines < 0:
            msg = "context_lines must be >= 0"
            raise ValidationError(msg, context={"field": "context_lines"})

    def _resolve_search_root(self, folder: str | None) -> Path:
        if folder is None:
            return self.vault_service.vault_path.resolve()

        normalized = self._normalize_api_path(folder)
        if normalized == "/":
            return self.vault_service.vault_path.resolve()

        relative_path = normalized.lstrip("/")
        try:
            resolved = validate_path_within_vault(
                relative_path,
                self.vault_service.vault_path,
                allow_symlinks=FOLLOW_SYMLINKS,
            )
        except PathValidationError as exc:
            msg = "Invalid folder path"
            raise ValidationError(
                msg,
                context={
                    "path": normalized,
                    "reason": "invalid_path",
                    "detail": str(exc),
                },
            ) from exc

        if not resolved.exists():
            msg = f"Folder not found: {normalized}"
            raise FileNotFoundError(msg)

        if not resolved.is_dir():
            msg = "Folder path is not a directory"
            raise ValidationError(
                msg,
                context={
                    "path": normalized,
                    "reason": "not_a_directory",
                },
            )

        return resolved

    def _search_filenames(
        self,
        request: SearchRequest,
        search_root: Path,
        show_hidden: bool,
        max_results: int,
    ) -> tuple[list[SearchMatch], bool]:
        results: list[SearchMatch] = []
        regex: re.Pattern[str] | None = None
        case_sensitive = self._is_smart_case_sensitive(request)

        if request.regex:
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                regex = re.compile(request.query, flags=flags)
            except re.error:
                return results, False

        vault_root = self.vault_service.vault_path.resolve()

        for file_path in self._iter_search_files(search_root, show_hidden):
            if self._globs_exclude(file_path, request.globs, search_root, vault_root):
                continue

            name = file_path.name
            stem = file_path.stem
            if not self._matches_filename(request, name, stem, regex, case_sensitive):
                continue

            relative_path = self._normalized_relative_path(file_path, vault_root)
            results.append(
                SearchMatch(
                    path=relative_path,
                    line=1,
                    column=1,
                    text=name,
                    context_before=[],
                    context_after=[],
                )
            )

            if len(results) > max_results:
                return results, True

        return results, False

    def _matches_filename(
        self,
        request: SearchRequest,
        name: str,
        stem: str,
        regex: re.Pattern[str] | None,
        case_sensitive: bool,
    ) -> bool:
        if request.regex:
            if regex is None:
                return False
            return regex.search(name) is not None or regex.search(stem) is not None

        if case_sensitive:
            return request.query in name or request.query in stem

        query = request.query.lower()
        return query in name.lower() or query in stem.lower()

    def _iter_search_files(self, search_root: Path, show_hidden: bool) -> Iterable[Path]:
        excluded_dirs = set(EXCLUDED_GLOBS)
        for root, dirnames, filenames in os.walk(search_root, followlinks=FOLLOW_SYMLINKS):
            dirnames[:] = [
                name
                for name in dirnames
                if name not in excluded_dirs and (show_hidden or not name.startswith("."))
            ]
            for filename in filenames:
                if not show_hidden and filename.startswith("."):
                    continue
                yield Path(root) / filename

    def _globs_exclude(
        self,
        file_path: Path,
        globs: list[str] | None,
        search_root: Path,
        vault_root: Path,
    ) -> bool:
        if not globs:
            return False
        relative_to_search = file_path.relative_to(search_root).as_posix()
        relative_to_root = file_path.relative_to(vault_root).as_posix()

        include_patterns: list[str] = []
        exclude_patterns: list[str] = []
        for pattern in globs:
            if pattern.startswith("!"):
                cleaned = pattern[1:]
                if cleaned:
                    exclude_patterns.append(cleaned)
                continue
            include_patterns.append(pattern)

        def matches_pattern(pattern: str) -> bool:
            return (
                Path(relative_to_search).match(pattern)
                or Path(relative_to_root).match(pattern)
                or Path(file_path.name).match(pattern)
            )

        if any(matches_pattern(pattern) for pattern in exclude_patterns):
            return True

        if not include_patterns:
            return False

        return all(not matches_pattern(pattern) for pattern in include_patterns)

    def _normalized_relative_path(self, path: Path, vault_root: Path) -> str:
        try:
            relative_path = path.resolve().relative_to(vault_root)
        except ValueError:
            return path.as_posix()
        return relative_path.as_posix()

    def _is_smart_case_sensitive(self, request: SearchRequest) -> bool:
        if request.case_sensitive:
            return True
        return any(char.isupper() for char in request.query)

    def _relative_search_path(self, search_root: Path) -> str:
        vault_root = self.vault_service.vault_path.resolve()
        try:
            relative_path = search_root.relative_to(vault_root)
        except ValueError:
            msg = "Search path is outside vault"
            raise SearchError(
                msg,
                context={"reason": "invalid_search_root"},
            )
        if relative_path == Path():
            return "."
        return relative_path.as_posix()

    def _normalize_api_path(self, api_path: str) -> str:
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

    async def _run_rg(self, args: Iterable[str]) -> tuple[str, str, int]:
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.vault_service.vault_path),
            )
        except FileNotFoundError as exc:
            msg = "ripgrep (rg) is not available"
            raise SearchError(msg, context={"reason": "rg_missing"}) from exc

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=SEARCH_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            msg = "Search timed out"
            raise SearchError(
                msg,
                context={
                    "reason": "timeout",
                    "timeout_seconds": SEARCH_TIMEOUT_SECONDS,
                },
            ) from exc

        exit_code = process.returncode if process.returncode is not None else 1
        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        return stdout_text, stderr_text, exit_code
