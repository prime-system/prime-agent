"""Tests for Claude Code session reader."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.services.claude_session_reader import ClaudeMessage, ClaudeSessionReader


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
    # Encode project path: /tmp/xyz/project -> -tmp-xyz-project
    encoded = str(temp_project_path).replace("/", "-")
    sessions_dir = temp_claude_home / "projects" / encoded
    sessions_dir.mkdir(parents=True)
    return sessions_dir


def create_test_session(sessions_dir: Path, session_id: str, messages: list[dict]) -> Path:
    """Create a test session JSONL file."""
    session_file = sessions_dir / f"{session_id}.jsonl"
    with session_file.open("w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")
    return session_file


def test_list_sessions_empty(temp_project_path: Path, temp_claude_home: Path):
    """Test listing sessions when no sessions exist."""
    reader = ClaudeSessionReader(temp_project_path, temp_claude_home)
    sessions = reader.list_sessions()
    assert sessions == []


def test_list_sessions_with_regular_session(
    temp_project_path: Path,
    temp_claude_home: Path,
    sessions_dir: Path,
):
    """Test listing a regular session."""
    session_id = "897e7d1e-5888-43c9-b7d3-36981060b3b2"
    messages = [
        {
            "type": "summary",
            "summary": "Test Session Summary",
        },
        {
            "type": "user",
            "uuid": "msg-1",
            "parentUuid": None,
            "timestamp": "2025-12-28T10:00:00.000Z",
            "message": {"role": "user", "content": "Hello"},
        },
        {
            "type": "assistant",
            "uuid": "msg-2",
            "parentUuid": "msg-1",
            "timestamp": "2025-12-28T10:00:05.000Z",
            "message": {"role": "assistant", "content": "Hi there!"},
        },
    ]
    create_test_session(sessions_dir, session_id, messages)

    reader = ClaudeSessionReader(temp_project_path, temp_claude_home)
    sessions = reader.list_sessions()

    assert len(sessions) == 1
    session = sessions[0]
    assert session["session_id"] == session_id
    assert session["is_agent_session"] is False
    assert session["message_count"] == 2
    assert session["summary"] == "Test Session Summary"
    assert session["created_at"] is not None
    assert session["last_activity"] is not None


def test_list_sessions_with_agent_session(
    temp_project_path: Path,
    temp_claude_home: Path,
    sessions_dir: Path,
):
    """Test listing an agent session."""
    session_id = "agent-a1917ad"
    messages = [
        {
            "type": "user",
            "uuid": "msg-1",
            "parentUuid": None,
            "timestamp": "2025-12-28T10:00:00.000Z",
            "isSidechain": True,
            "agentId": "a1917ad",
            "message": {"role": "user", "content": "Agent task"},
        },
    ]
    create_test_session(sessions_dir, session_id, messages)

    reader = ClaudeSessionReader(temp_project_path, temp_claude_home)

    # Should not include agent sessions by default
    sessions = reader.list_sessions(include_agent_sessions=False)
    assert len(sessions) == 0

    # Should include when requested
    sessions = reader.list_sessions(include_agent_sessions=True)
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == session_id
    assert sessions[0]["is_agent_session"] is True


def test_get_session(
    temp_project_path: Path,
    temp_claude_home: Path,
    sessions_dir: Path,
):
    """Test getting a complete session."""
    session_id = "test-session-123"
    messages = [
        {
            "type": "summary",
            "summary": "Test Summary",
        },
        {
            "type": "user",
            "uuid": "msg-1",
            "parentUuid": None,
            "timestamp": "2025-12-28T10:00:00.000Z",
            "message": {"role": "user", "content": "First message"},
        },
        {
            "type": "assistant",
            "uuid": "msg-2",
            "parentUuid": "msg-1",
            "timestamp": "2025-12-28T10:00:05.000Z",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Response"}],
            },
        },
    ]
    create_test_session(sessions_dir, session_id, messages)

    reader = ClaudeSessionReader(temp_project_path, temp_claude_home)
    session = reader.get_session(session_id)

    assert session is not None
    assert session.session_id == session_id
    assert session.summary == "Test Summary"
    assert len(session.messages) == 2  # Excludes summary line
    assert session.message_count == 2

    # Check first message
    msg1 = session.messages[0]
    assert msg1.uuid == "msg-1"
    assert msg1.parent_uuid is None
    assert msg1.type == "user"
    assert msg1.role == "user"
    assert msg1.content == "First message"

    # Check second message
    msg2 = session.messages[1]
    assert msg2.uuid == "msg-2"
    assert msg2.parent_uuid == "msg-1"
    assert msg2.role == "assistant"
    assert msg2.content == "Response"  # Extracted from content array


def test_get_session_not_found(temp_project_path: Path, temp_claude_home: Path):
    """Test getting a non-existent session."""
    reader = ClaudeSessionReader(temp_project_path, temp_claude_home)
    session = reader.get_session("nonexistent")
    assert session is None


def test_session_ordering(
    temp_project_path: Path,
    temp_claude_home: Path,
    sessions_dir: Path,
):
    """Test that sessions are ordered by last activity (newest first)."""
    # Create three sessions with different timestamps
    create_test_session(
        sessions_dir,
        "session-1",
        [
            {
                "type": "user",
                "uuid": "msg-1",
                "timestamp": "2025-12-28T10:00:00.000Z",
                "message": {"role": "user", "content": "Old"},
            }
        ],
    )
    create_test_session(
        sessions_dir,
        "session-2",
        [
            {
                "type": "user",
                "uuid": "msg-2",
                "timestamp": "2025-12-28T12:00:00.000Z",
                "message": {"role": "user", "content": "Newest"},
            }
        ],
    )
    create_test_session(
        sessions_dir,
        "session-3",
        [
            {
                "type": "user",
                "uuid": "msg-3",
                "timestamp": "2025-12-28T11:00:00.000Z",
                "message": {"role": "user", "content": "Middle"},
            }
        ],
    )

    reader = ClaudeSessionReader(temp_project_path, temp_claude_home)
    sessions = reader.list_sessions()

    assert len(sessions) == 3
    # Should be ordered by last activity, newest first
    assert sessions[0]["session_id"] == "session-2"
    assert sessions[1]["session_id"] == "session-3"
    assert sessions[2]["session_id"] == "session-1"


def test_session_ordering_tie_breaker(
    temp_project_path: Path,
    temp_claude_home: Path,
    sessions_dir: Path,
):
    """Test that sessions with same activity use session_id as tie-breaker."""
    timestamp = "2025-12-28T10:00:00.000Z"
    create_test_session(
        sessions_dir,
        "session-b",
        [
            {
                "type": "user",
                "uuid": "msg-1",
                "timestamp": timestamp,
                "message": {"role": "user", "content": "Same time"},
            }
        ],
    )
    create_test_session(
        sessions_dir,
        "session-a",
        [
            {
                "type": "user",
                "uuid": "msg-2",
                "timestamp": timestamp,
                "message": {"role": "user", "content": "Same time"},
            }
        ],
    )

    reader = ClaudeSessionReader(temp_project_path, temp_claude_home)
    sessions = reader.list_sessions()

    assert [session["session_id"] for session in sessions] == ["session-b", "session-a"]


def test_message_content_extraction():
    """Test message content extraction from different formats."""
    # String content
    msg1 = ClaudeMessage(
        uuid="1",
        parent_uuid=None,
        timestamp=datetime.now(UTC),
        type="user",
        message={"role": "user", "content": "Simple text"},
    )
    assert msg1.content == "Simple text"

    # Array content with text blocks
    msg2 = ClaudeMessage(
        uuid="2",
        parent_uuid=None,
        timestamp=datetime.now(UTC),
        type="assistant",
        message={
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Part 1"},
                {"type": "text", "text": "Part 2"},
            ],
        },
    )
    assert msg2.content == "Part 1\nPart 2"

    # No message
    msg3 = ClaudeMessage(
        uuid="3",
        parent_uuid=None,
        timestamp=datetime.now(UTC),
        type="summary",
        message=None,
    )
    assert msg3.content is None


def test_invalid_json_handling(
    temp_project_path: Path,
    temp_claude_home: Path,
    sessions_dir: Path,
):
    """Test that invalid JSON lines are skipped gracefully."""
    session_id = "test-invalid"
    session_file = sessions_dir / f"{session_id}.jsonl"

    with session_file.open("w", encoding="utf-8") as f:
        # Valid line
        f.write(
            json.dumps(
                {
                    "type": "user",
                    "uuid": "msg-1",
                    "timestamp": "2025-12-28T10:00:00.000Z",
                    "message": {"role": "user", "content": "Valid"},
                }
            )
            + "\n"
        )
        # Invalid JSON
        f.write("{ invalid json }\n")
        # Another valid line
        f.write(
            json.dumps(
                {
                    "type": "assistant",
                    "uuid": "msg-2",
                    "timestamp": "2025-12-28T10:00:05.000Z",
                    "message": {"role": "assistant", "content": "Also valid"},
                }
            )
            + "\n"
        )

    reader = ClaudeSessionReader(temp_project_path, temp_claude_home)
    session = reader.get_session(session_id)

    # Should have 2 valid messages, skipping the invalid line
    assert session is not None
    assert len(session.messages) == 2
    assert session.messages[0].content == "Valid"
    assert session.messages[1].content == "Also valid"
