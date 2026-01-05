"""Tests for Claude session API service."""

import json
from pathlib import Path

import pytest

from app.services.claude_session_api import ClaudeSessionAPI


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
    encoded = str(temp_project_path).replace("/", "-")
    sessions_dir = temp_claude_home / "projects" / encoded
    sessions_dir.mkdir(parents=True)
    return sessions_dir


def create_test_session(sessions_dir: Path, session_id: str, summary: str) -> None:
    """Create a test session JSONL file."""
    session_file = sessions_dir / f"{session_id}.jsonl"
    messages = [
        {"type": "summary", "summary": summary},
        {
            "type": "user",
            "uuid": "msg-1",
            "timestamp": "2025-12-28T10:00:00.000Z",
            "message": {"role": "user", "content": "Test message"},
        },
    ]
    with session_file.open("w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")


def test_list_sessions(
    temp_project_path: Path,
    temp_claude_home: Path,
    sessions_dir: Path,
):
    """Test listing sessions via API."""
    create_test_session(sessions_dir, "session-1", "First session")
    create_test_session(sessions_dir, "session-2", "Second session")

    api = ClaudeSessionAPI(temp_project_path, temp_claude_home)
    sessions = api.list_sessions()

    assert len(sessions) == 2
    assert all("session_id" in s for s in sessions)
    assert all("summary" in s for s in sessions)


def test_list_sessions_with_limit(
    temp_project_path: Path,
    temp_claude_home: Path,
    sessions_dir: Path,
):
    """Test listing sessions with limit."""
    for i in range(5):
        create_test_session(sessions_dir, f"session-{i}", f"Session {i}")

    api = ClaudeSessionAPI(temp_project_path, temp_claude_home)
    sessions = api.list_sessions(limit=3)

    assert len(sessions) == 3


def test_get_session(
    temp_project_path: Path,
    temp_claude_home: Path,
    sessions_dir: Path,
):
    """Test getting a complete session."""
    session_id = "test-session"
    create_test_session(sessions_dir, session_id, "Test Session")

    api = ClaudeSessionAPI(temp_project_path, temp_claude_home)
    session = api.get_session(session_id)

    assert session is not None
    assert session["session_id"] == session_id
    assert session["summary"] == "Test Session"
    assert "messages" in session
    assert len(session["messages"]) == 1


def test_get_session_not_found(temp_project_path: Path, temp_claude_home: Path):
    """Test getting a non-existent session."""
    api = ClaudeSessionAPI(temp_project_path, temp_claude_home)
    session = api.get_session("nonexistent")
    assert session is None


def test_get_session_messages(
    temp_project_path: Path,
    temp_claude_home: Path,
    sessions_dir: Path,
):
    """Test getting messages from a session."""
    session_id = "test-session"
    session_file = sessions_dir / f"{session_id}.jsonl"

    messages = [
        {
            "type": "user",
            "uuid": "msg-1",
            "timestamp": "2025-12-28T10:00:00.000Z",
            "message": {"role": "user", "content": "User message"},
        },
        {
            "type": "assistant",
            "uuid": "msg-2",
            "timestamp": "2025-12-28T10:00:05.000Z",
            "message": {"role": "assistant", "content": "Assistant message"},
        },
        {
            "type": "file-history-snapshot",
            "uuid": "msg-3",
            "timestamp": "2025-12-28T10:00:10.000Z",
        },
    ]

    with session_file.open("w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")

    api = ClaudeSessionAPI(temp_project_path, temp_claude_home)
    messages = api.get_session_messages(session_id)

    # Should return only user and assistant messages, not file-history-snapshot
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"


def test_get_session_messages_filtered_by_role(
    temp_project_path: Path,
    temp_claude_home: Path,
    sessions_dir: Path,
):
    """Test getting messages filtered by role."""
    session_id = "test-session"
    session_file = sessions_dir / f"{session_id}.jsonl"

    messages = [
        {
            "type": "user",
            "uuid": "msg-1",
            "timestamp": "2025-12-28T10:00:00.000Z",
            "message": {"role": "user", "content": "User 1"},
        },
        {
            "type": "assistant",
            "uuid": "msg-2",
            "timestamp": "2025-12-28T10:00:05.000Z",
            "message": {"role": "assistant", "content": "Assistant"},
        },
        {
            "type": "user",
            "uuid": "msg-3",
            "timestamp": "2025-12-28T10:00:10.000Z",
            "message": {"role": "user", "content": "User 2"},
        },
    ]

    with session_file.open("w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")

    api = ClaudeSessionAPI(temp_project_path, temp_claude_home)
    user_messages = api.get_session_messages(session_id, roles=["user"])

    assert len(user_messages) == 2
    assert all(msg["role"] == "user" for msg in user_messages)


def test_get_session_summary(
    temp_project_path: Path,
    temp_claude_home: Path,
    sessions_dir: Path,
):
    """Test getting session summary without loading messages."""
    session_id = "test-session"
    create_test_session(sessions_dir, session_id, "Test Summary")

    api = ClaudeSessionAPI(temp_project_path, temp_claude_home)
    summary = api.get_session_summary(session_id)

    assert summary is not None
    assert summary["session_id"] == session_id
    assert summary["summary"] == "Test Summary"
    # Should not include full messages
    assert "messages" not in summary


def test_search_sessions(
    temp_project_path: Path,
    temp_claude_home: Path,
    sessions_dir: Path,
):
    """Test searching sessions by query."""
    create_test_session(sessions_dir, "session-1", "Feature: user authentication")
    create_test_session(sessions_dir, "session-2", "Bug fix: database connection")
    create_test_session(sessions_dir, "session-3", "Feature: password reset")

    api = ClaudeSessionAPI(temp_project_path, temp_claude_home)

    # Search for "feature"
    results = api.search_sessions(query="feature")
    assert len(results) == 2
    assert all("feature" in s["summary"].lower() for s in results)

    # Search for "database"
    results = api.search_sessions(query="database")
    assert len(results) == 1
    assert "database" in results[0]["summary"].lower()


def test_search_sessions_with_limit(
    temp_project_path: Path,
    temp_claude_home: Path,
    sessions_dir: Path,
):
    """Test search with result limit."""
    for i in range(5):
        create_test_session(sessions_dir, f"session-{i}", f"Feature {i}")

    api = ClaudeSessionAPI(temp_project_path, temp_claude_home)
    results = api.search_sessions(query="feature", limit=3)

    assert len(results) == 3
