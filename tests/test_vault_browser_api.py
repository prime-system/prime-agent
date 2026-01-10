"""API tests for vault browser endpoints."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.container import init_container
from app.services.vault import VaultService


@pytest.fixture
def vault_browser_client(temp_vault: Path):
    """Create a TestClient with the vault browser router."""
    from app.api import vault_browser

    app = FastAPI()
    app.include_router(vault_browser.router)

    vault_service = VaultService(str(temp_vault))
    vault_service.ensure_structure()

    init_container(
        vault_service=vault_service,
        git_service=MagicMock(),
        inbox_service=MagicMock(),
        agent_service=MagicMock(),
        log_service=MagicMock(),
        chat_session_manager=MagicMock(),
        agent_chat_service=MagicMock(),
        agent_session_manager=MagicMock(),
        relay_client=MagicMock(),
        claude_session_api=MagicMock(),
        health_service=MagicMock(),
        command_service=MagicMock(),
        agent_identity_service=MagicMock(),
    )

    with TestClient(app) as client:
        yield client


def test_list_folder_requires_auth(vault_browser_client: TestClient) -> None:
    """Requests without auth should be rejected."""
    response = vault_browser_client.get("/api/v1/vault/folders", params={"path": "/"})
    assert response.status_code == 401


def test_list_folder_etag_varies_with_show_hidden(
    vault_browser_client: TestClient,
    temp_vault: Path,
    auth_headers: dict[str, str],
) -> None:
    """ETag should differ when showHidden changes."""
    (temp_vault / "visible.txt").write_text("visible")
    (temp_vault / ".hidden.txt").write_text("hidden")

    response = vault_browser_client.get(
        "/api/v1/vault/folders",
        params={"path": "/"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    etag_default = response.headers.get("ETag")
    assert etag_default
    names_default = {item["name"] for item in response.json()["items"]}
    assert ".hidden.txt" not in names_default

    response_hidden = vault_browser_client.get(
        "/api/v1/vault/folders",
        params={"path": "/", "showHidden": "true"},
        headers=auth_headers,
    )
    assert response_hidden.status_code == 200
    etag_hidden = response_hidden.headers.get("ETag")
    assert etag_hidden
    assert etag_default != etag_hidden
    names_hidden = {item["name"] for item in response_hidden.json()["items"]}
    assert ".hidden.txt" in names_hidden


def test_file_metadata_etag_support(
    vault_browser_client: TestClient,
    temp_vault: Path,
    auth_headers: dict[str, str],
) -> None:
    """File metadata should support If-None-Match."""
    file_path = temp_vault / "readme.md"
    file_path.write_text("hello")

    response = vault_browser_client.get(
        "/api/v1/vault/files/meta",
        params={"path": "/readme.md"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    etag = response.headers.get("ETag")
    assert etag

    response_cached = vault_browser_client.get(
        "/api/v1/vault/files/meta",
        params={"path": "/readme.md"},
        headers={**auth_headers, "If-None-Match": etag},
    )
    assert response_cached.status_code == 304


def test_file_content_range_requests(
    vault_browser_client: TestClient,
    temp_vault: Path,
    auth_headers: dict[str, str],
) -> None:
    """Range requests should return partial content and headers."""
    file_path = temp_vault / "sample.txt"
    file_path.write_text("abcdef")

    response = vault_browser_client.get(
        "/api/v1/vault/files/content",
        params={"path": "/sample.txt"},
        headers={**auth_headers, "Range": "bytes=1-3"},
    )
    assert response.status_code == 206
    assert response.content == b"bcd"
    assert response.headers.get("Content-Range") == "bytes 1-3/6"
    assert response.headers.get("Accept-Ranges") == "bytes"


def test_invalid_range_returns_416(
    vault_browser_client: TestClient,
    temp_vault: Path,
    auth_headers: dict[str, str],
) -> None:
    """Invalid ranges should return 416."""
    file_path = temp_vault / "sample.txt"
    file_path.write_text("abcdef")

    response = vault_browser_client.get(
        "/api/v1/vault/files/content",
        params={"path": "/sample.txt"},
        headers={**auth_headers, "Range": "bytes=100-200"},
    )
    assert response.status_code == 416


def test_path_traversal_rejected(
    vault_browser_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Path traversal attempts should be rejected."""
    response = vault_browser_client.get(
        "/api/v1/vault/folders",
        params={"path": "/../etc"},
        headers=auth_headers,
    )
    assert response.status_code == 400


def test_symlink_metadata_returns_not_found(
    vault_browser_client: TestClient,
    temp_vault: Path,
    auth_headers: dict[str, str],
) -> None:
    """Symlink access should be blocked."""
    target = temp_vault / "target.txt"
    target.write_text("target")
    symlink = temp_vault / "link.txt"
    try:
        symlink.symlink_to(target)
    except OSError:
        pytest.skip("Symlink creation not supported on this platform")

    response = vault_browser_client.get(
        "/api/v1/vault/files/meta",
        params={"path": "/link.txt"},
        headers=auth_headers,
    )
    assert response.status_code == 404
