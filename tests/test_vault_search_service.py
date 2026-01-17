"""Tests for VaultSearchService."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.exceptions import ValidationError
from app.models.vault_search import SearchRequest
from app.services.vault import VaultService
from app.services.vault_search import build_rg_args, parse_rg_output, VaultSearchService


def test_build_rg_args_includes_expected_flags() -> None:
    """rg args should include flags and exclusions based on request."""
    request = SearchRequest(
        query="Project plan",
        regex=False,
        case_sensitive=False,
        globs=["*.md", "Notes/**"],
        max_results=200,
        context_lines=2,
    )

    args = build_rg_args(request, show_hidden=True, search_path="Notes")

    assert args[0] == "rg"
    assert "--json" in args
    assert "--fixed-strings" in args
    assert "--smart-case" in args
    assert "--hidden" in args
    assert "--context" in args
    assert "2" in args
    assert "!.git/**" in args
    assert "--" in args
    assert "*.md" in args
    assert "Notes/**" in args
    assert args[-3] == "--"
    assert args[-2:] == ["Project plan", "Notes"]


def test_parse_rg_output_with_context() -> None:
    """rg JSON parsing should include context and column info."""
    payloads = [
        {
            "type": "context",
            "data": {
                "path": {"text": "Notes/alpha.md"},
                "lines": {"text": "before\n"},
                "line_number": 1,
                "submatches": [],
            },
        },
        {
            "type": "match",
            "data": {
                "path": {"text": "Notes/alpha.md"},
                "lines": {"text": "hello match\n"},
                "line_number": 2,
                "submatches": [{"match": {"text": "match"}, "start": 6, "end": 11}],
            },
        },
        {
            "type": "context",
            "data": {
                "path": {"text": "Notes/alpha.md"},
                "lines": {"text": "after\n"},
                "line_number": 3,
                "submatches": [],
            },
        },
    ]
    output = "\n".join(json.dumps(payload) for payload in payloads)

    results = parse_rg_output(output, Path("/vault"), context_lines=1)

    assert len(results) == 1
    match = results[0]
    assert match.path == "Notes/alpha.md"
    assert match.line == 2
    assert match.column == 7
    assert match.text == "hello match"
    assert match.context_before == ["before"]
    assert match.context_after == ["after"]


@pytest.mark.asyncio
async def test_search_truncates_results(temp_vault: Path) -> None:
    """Search should report truncation when max_results is exceeded."""
    if shutil.which("rg") is None:
        pytest.skip("ripgrep not available")

    vault_service = VaultService(str(temp_vault))
    vault_service.ensure_structure()
    notes_dir = temp_vault / "Notes"
    notes_dir.mkdir()
    (notes_dir / "one.md").write_text("beta\n")
    (notes_dir / "two.md").write_text("beta\n")

    search_service = VaultSearchService(vault_service=vault_service)
    request = SearchRequest(query="beta", max_results=1)
    response = await search_service.search(request)

    assert response.total_matches == 1
    assert response.truncated is True


@pytest.mark.asyncio
async def test_search_respects_show_hidden(temp_vault: Path) -> None:
    """Hidden files should be searchable only when show_hidden is enabled."""
    if shutil.which("rg") is None:
        pytest.skip("ripgrep not available")

    vault_service = VaultService(str(temp_vault))
    vault_service.ensure_structure()
    hidden_file = temp_vault / ".hidden.md"
    hidden_file.write_text("secret")

    search_service = VaultSearchService(vault_service=vault_service)
    request = SearchRequest(query="secret", max_results=5)

    response = await search_service.search(request, show_hidden=False)
    assert response.total_matches == 0

    response_hidden = await search_service.search(request, show_hidden=True)
    assert any(match.path == ".hidden.md" for match in response_hidden.results)


@pytest.mark.asyncio
async def test_search_matches_filename_when_content_missing(temp_vault: Path) -> None:
    """Search should match file names even when content does not match."""
    if shutil.which("rg") is None:
        pytest.skip("ripgrep not available")

    vault_service = VaultService(str(temp_vault))
    vault_service.ensure_structure()
    logs_dir = temp_vault / "08-Logs"
    logs_dir.mkdir()
    target_name = "command-positiveMessage-2026-01-13T16-45-51Z.md"
    (logs_dir / target_name).write_text("unrelated content")

    search_service = VaultSearchService(vault_service=vault_service)
    request = SearchRequest(query="command-positiveMessage-2026-01-13T16-45-51Z")
    response = await search_service.search(request)

    assert any(match.path == f"08-Logs/{target_name}" for match in response.results)


@pytest.mark.asyncio
async def test_search_filename_priority_over_content(temp_vault: Path) -> None:
    """Filename matches should appear before content matches."""
    if shutil.which("rg") is None:
        pytest.skip("ripgrep not available")

    vault_service = VaultService(str(temp_vault))
    vault_service.ensure_structure()
    notes_dir = temp_vault / "Notes"
    notes_dir.mkdir()
    (notes_dir / "report.md").write_text("unrelated content")
    (notes_dir / "meeting.md").write_text("report")

    search_service = VaultSearchService(vault_service=vault_service)
    request = SearchRequest(query="report", max_results=1)
    response = await search_service.search(request)

    assert response.results[0].path == "Notes/report.md"


@pytest.mark.asyncio
async def test_search_preserves_multiple_matches_in_same_file(temp_vault: Path) -> None:
    """Search should return multiple content matches from the same file."""
    if shutil.which("rg") is None:
        pytest.skip("ripgrep not available")

    vault_service = VaultService(str(temp_vault))
    vault_service.ensure_structure()
    notes_dir = temp_vault / "Notes"
    notes_dir.mkdir()
    target_name = "match-report.md"
    (notes_dir / target_name).write_text("match\nmatch\n")

    search_service = VaultSearchService(vault_service=vault_service)
    request = SearchRequest(query="match", max_results=10)
    response = await search_service.search(request)

    matches = [match for match in response.results if match.path == f"Notes/{target_name}"]
    lines = {match.line for match in matches}
    assert {1, 2}.issubset(lines)


@pytest.mark.asyncio
async def test_search_filename_respects_smart_case(temp_vault: Path) -> None:
    """Filename search should follow smart-case when case_sensitive is false."""
    if shutil.which("rg") is None:
        pytest.skip("ripgrep not available")

    vault_service = VaultService(str(temp_vault))
    vault_service.ensure_structure()
    notes_dir = temp_vault / "Notes"
    notes_dir.mkdir()
    (notes_dir / "report.md").write_text("unrelated")

    search_service = VaultSearchService(vault_service=vault_service)
    request = SearchRequest(query="Report", case_sensitive=False)
    response = await search_service.search(request)

    assert response.total_matches == 0


@pytest.mark.asyncio
async def test_search_filename_respects_negative_globs(temp_vault: Path) -> None:
    """Filename search should honor exclude globs."""
    if shutil.which("rg") is None:
        pytest.skip("ripgrep not available")

    vault_service = VaultService(str(temp_vault))
    vault_service.ensure_structure()
    notes_dir = temp_vault / "Notes"
    notes_dir.mkdir()
    (notes_dir / "alpha.md").write_text("alpha")

    search_service = VaultSearchService(vault_service=vault_service)
    request = SearchRequest(query="alpha", globs=["!Notes/**"])
    response = await search_service.search(request)

    assert response.total_matches == 0


@pytest.mark.asyncio
async def test_search_invalid_regex_raises(temp_vault: Path) -> None:
    """Invalid regex should raise ValidationError."""
    if shutil.which("rg") is None:
        pytest.skip("ripgrep not available")

    vault_service = VaultService(str(temp_vault))
    vault_service.ensure_structure()

    search_service = VaultSearchService(vault_service=vault_service)
    request = SearchRequest(query="[", regex=True)

    with pytest.raises(ValidationError):
        await search_service.search(request)


@pytest.mark.asyncio
async def test_search_rejects_invalid_folder(temp_vault: Path) -> None:
    """Invalid folder paths should be rejected."""
    vault_service = VaultService(str(temp_vault))
    vault_service.ensure_structure()

    search_service = VaultSearchService(vault_service=vault_service)
    request = SearchRequest(query="test", folder="/../etc")

    with pytest.raises(ValidationError):
        await search_service.search(request)
