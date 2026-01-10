"""Tests for VaultBrowserService."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.exceptions import ValidationError
from app.services.vault import VaultService
from app.services.vault_browser import VaultBrowserService


@pytest.fixture
def vault_browser_service(temp_vault: Path) -> VaultBrowserService:
    """Create a VaultBrowserService with a temporary vault."""
    vault_service = VaultService(str(temp_vault))
    vault_service.ensure_structure()
    return VaultBrowserService(vault_service=vault_service)


@pytest.mark.asyncio
async def test_list_folder_filters_hidden(vault_browser_service: VaultBrowserService) -> None:
    """Hidden files should be excluded unless show_hidden is set."""
    vault_path = vault_browser_service.vault_service.vault_path
    (vault_path / "visible.txt").write_text("visible")
    (vault_path / ".hidden.txt").write_text("hidden")

    items = await vault_browser_service.list_folder("/", show_hidden=False)
    names = {item.name for item in items}
    assert "visible.txt" in names
    assert ".hidden.txt" not in names

    items_with_hidden = await vault_browser_service.list_folder("/", show_hidden=True)
    names_with_hidden = {item.name for item in items_with_hidden}
    assert ".hidden.txt" in names_with_hidden


@pytest.mark.asyncio
async def test_list_folder_skips_symlinks(vault_browser_service: VaultBrowserService) -> None:
    """Symlink entries should be skipped in listings."""
    vault_path = vault_browser_service.vault_service.vault_path
    target = vault_path / "target.txt"
    target.write_text("target")
    symlink = vault_path / "link.txt"
    try:
        symlink.symlink_to(target)
    except OSError:
        pytest.skip("Symlink creation not supported on this platform")

    items = await vault_browser_service.list_folder("/", show_hidden=True)
    names = {item.name for item in items}
    assert "link.txt" not in names


@pytest.mark.asyncio
async def test_get_file_metadata_returns_etag(
    vault_browser_service: VaultBrowserService,
) -> None:
    """File metadata should include size and etag."""
    vault_path = vault_browser_service.vault_service.vault_path
    file_path = vault_path / "notes.md"
    file_path.write_text("hello")

    metadata = await vault_browser_service.get_file_metadata("/notes.md")
    assert metadata.size == file_path.stat().st_size
    assert metadata.etag
    assert metadata.path == "/notes.md"


@pytest.mark.asyncio
async def test_invalid_path_rejected(vault_browser_service: VaultBrowserService) -> None:
    """Path traversal attempts should be rejected."""
    with pytest.raises(ValidationError):
        await vault_browser_service.list_folder("/../etc", show_hidden=False)


@pytest.mark.asyncio
async def test_get_file_metadata_on_folder_raises(
    vault_browser_service: VaultBrowserService,
) -> None:
    """Requesting file metadata for a folder should raise."""
    vault_path = vault_browser_service.vault_service.vault_path
    folder_path = vault_path / "Daily"
    folder_path.mkdir()

    with pytest.raises(IsADirectoryError):
        await vault_browser_service.get_file_metadata("/Daily")
