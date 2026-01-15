"""Tests for Claude sessions API pagination."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import claude_sessions
from app.dependencies import get_agent_session_manager, get_claude_session_api
from app.services.claude_session_api import ClaudeSessionAPI
from app.utils.path_encoder import encode_project_path


@pytest.fixture
def temp_claude_home(tmp_path: Path) -> Path:
    """Create temporary Claude home directory."""
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()
    return claude_home


@pytest.fixture
def temp_project_path(tmp_path: Path) -> Path:
    """Create temporary project directory."""
    project = tmp_path / "project"
    project.mkdir()
    return project


@pytest.fixture
def sessions_dir(temp_claude_home: Path, temp_project_path: Path) -> Path:
    """Create sessions directory for project."""
    encoded = encode_project_path(temp_project_path)
    sessions_dir = temp_claude_home / "projects" / encoded
    sessions_dir.mkdir(parents=True)
    return sessions_dir


@pytest.fixture
def agent_session_manager() -> MagicMock:
    """Create a mock AgentSessionManager."""
    manager = MagicMock()
    manager.get_running_session_ids = AsyncMock(return_value=set())
    return manager


@pytest.fixture
def client(
    temp_project_path: Path,
    temp_claude_home: Path,
    agent_session_manager: MagicMock,
) -> TestClient:
    """Create a test client with the Claude sessions router."""
    api = ClaudeSessionAPI(temp_project_path, temp_claude_home)
    app = FastAPI()
    app.include_router(claude_sessions.router)
    app.dependency_overrides[get_claude_session_api] = lambda: api
    app.dependency_overrides[get_agent_session_manager] = lambda: agent_session_manager
    return TestClient(app)


def create_test_session(
    sessions_dir: Path,
    session_id: str,
    summary: str,
    timestamp: str,
) -> None:
    """Create a test session JSONL file."""
    session_file = sessions_dir / f"{session_id}.jsonl"
    messages = [
        {"type": "summary", "summary": summary},
        {
            "type": "user",
            "uuid": f"{session_id}-msg",
            "timestamp": timestamp,
            "message": {"role": "user", "content": "Test message"},
        },
    ]
    with session_file.open("w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")


def test_list_sessions_cursor_pagination(
    client: TestClient,
    sessions_dir: Path,
) -> None:
    create_test_session(
        sessions_dir,
        "session-0",
        "Session 0",
        "2025-12-28T10:00:00.000Z",
    )
    create_test_session(
        sessions_dir,
        "session-1",
        "Session 1",
        "2025-12-28T11:00:00.000Z",
    )
    create_test_session(
        sessions_dir,
        "session-2",
        "Session 2",
        "2025-12-28T12:00:00.000Z",
    )

    response = client.get("/api/v1/claude-sessions", params={"limit": 2})
    assert response.status_code == 200
    payload = response.json()

    assert payload["total"] == 2
    assert payload["has_more"] is True
    assert payload["next_cursor"] is not None
    assert [session["session_id"] for session in payload["sessions"]] == [
        "session-2",
        "session-1",
    ]
    assert all("is_running" in session for session in payload["sessions"])
    assert all(session["is_running"] is False for session in payload["sessions"])

    response2 = client.get(
        "/api/v1/claude-sessions",
        params={"limit": 2, "cursor": payload["next_cursor"]},
    )
    assert response2.status_code == 200
    payload2 = response2.json()

    assert payload2["total"] == 1
    assert payload2["has_more"] is False
    assert payload2["next_cursor"] is None
    assert [session["session_id"] for session in payload2["sessions"]] == ["session-0"]
    assert all("is_running" in session for session in payload2["sessions"])
    assert all(session["is_running"] is False for session in payload2["sessions"])


def test_list_sessions_invalid_cursor(client: TestClient) -> None:
    response = client.get("/api/v1/claude-sessions", params={"cursor": "not-base64"})
    assert response.status_code == 400
    payload = response.json()
    assert payload["error"] == "InvalidCursor"


def test_list_sessions_query_with_cursor(
    client: TestClient,
    sessions_dir: Path,
) -> None:
    create_test_session(
        sessions_dir,
        "alpha-1",
        "Alpha session one",
        "2025-12-28T12:00:00.000Z",
    )
    create_test_session(
        sessions_dir,
        "alpha-0",
        "Alpha session two",
        "2025-12-28T11:00:00.000Z",
    )
    create_test_session(
        sessions_dir,
        "beta-0",
        "Beta session",
        "2025-12-28T10:00:00.000Z",
    )

    response = client.get(
        "/api/v1/claude-sessions",
        params={"limit": 1, "query": "alpha"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["total"] == 1
    assert payload["has_more"] is True
    assert payload["next_cursor"] is not None
    assert [session["session_id"] for session in payload["sessions"]] == ["alpha-1"]
    assert all("is_running" in session for session in payload["sessions"])
    assert all(session["is_running"] is False for session in payload["sessions"])

    response2 = client.get(
        "/api/v1/claude-sessions",
        params={"limit": 1, "query": "alpha", "cursor": payload["next_cursor"]},
    )
    assert response2.status_code == 200
    payload2 = response2.json()

    assert payload2["total"] == 1
    assert payload2["has_more"] is False
    assert payload2["next_cursor"] is None
    assert [session["session_id"] for session in payload2["sessions"]] == ["alpha-0"]
    assert all("is_running" in session for session in payload2["sessions"])
    assert all(session["is_running"] is False for session in payload2["sessions"])


def test_list_sessions_running_flag(
    client: TestClient,
    sessions_dir: Path,
    agent_session_manager: MagicMock,
) -> None:
    create_test_session(
        sessions_dir,
        "session-1",
        "Session 1",
        "2025-12-28T11:00:00.000Z",
    )
    create_test_session(
        sessions_dir,
        "session-2",
        "Session 2",
        "2025-12-28T12:00:00.000Z",
    )

    agent_session_manager.get_running_session_ids.return_value = {"session-2"}

    response = client.get("/api/v1/claude-sessions")
    assert response.status_code == 200
    payload = response.json()

    running_flags = {
        session["session_id"]: session["is_running"] for session in payload["sessions"]
    }
    assert running_flags["session-2"] is True
    assert running_flags["session-1"] is False
