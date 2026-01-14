"""Reader for Claude Code's native JSONL session logs."""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.utils.path_encoder import get_project_sessions_dir

logger = logging.getLogger(__name__)


@dataclass
class ClaudeMessage:
    """Represents a message in a Claude Code session."""

    uuid: str
    parent_uuid: str | None
    timestamp: datetime
    type: str  # "user", "assistant", "summary", "file-history-snapshot"
    message: dict[str, Any] | None = None
    is_sidechain: bool = False
    agent_id: str | None = None

    @property
    def role(self) -> str | None:
        """Extract role from message content."""
        if not self.message:
            return None
        return self.message.get("role")

    @property
    def content(self) -> str | None:
        """Extract text content from message."""
        if not self.message:
            return None

        content = self.message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            # Extract text blocks from content array
            text_blocks = [
                block.get("text", "") for block in content if block.get("type") == "text"
            ]
            return "\n".join(text_blocks)
        return ""


@dataclass
class ClaudeSession:
    """Represents a Claude Code session with metadata and messages."""

    session_id: str
    file_path: Path
    summary: str | None = None
    messages: list[ClaudeMessage] = field(default_factory=list)
    is_agent_session: bool = False
    agent_id: str | None = None

    @property
    def created_at(self) -> datetime | None:
        """Get session creation time from first message."""
        if not self.messages:
            return None
        return self.messages[0].timestamp

    @property
    def last_activity(self) -> datetime | None:
        """Get last activity time from last message."""
        if not self.messages:
            return None
        return self.messages[-1].timestamp

    @property
    def message_count(self) -> int:
        """Get count of user/assistant messages (excluding system messages)."""
        return sum(
            1
            for msg in self.messages
            if msg.type in ("user", "assistant") and msg.role in ("user", "assistant")
        )


class ClaudeSessionReader:
    """Reads Claude Code session logs from JSONL files."""

    def __init__(
        self,
        project_path: str | Path,
        claude_home: str | Path = "/home/prime/.claude",
    ):
        """
        Initialize session reader.

        Args:
            project_path: Absolute path to project directory
            claude_home: Path to Claude Code home directory
        """
        self.project_path = Path(project_path)
        self.claude_home = Path(claude_home)
        self.sessions_dir = get_project_sessions_dir(project_path, claude_home)

    def list_sessions(
        self,
        include_agent_sessions: bool = True,
    ) -> list[dict[str, Any]]:
        """
        List all available sessions for the project.

        Args:
            include_agent_sessions: Whether to include agent/sidechain sessions

        Returns:
            List of session metadata dictionaries with keys:
            - session_id: Session UUID or agent ID
            - file_path: Path to JSONL file
            - is_agent_session: Whether this is an agent session
            - created_at: Creation timestamp (if available)
            - last_activity: Last activity timestamp (if available)
            - message_count: Number of messages (if available)
        """
        if not self.sessions_dir.exists():
            logger.warning(
                "Claude sessions directory not found: %s",
                self.sessions_dir,
            )
            return []

        sessions = []
        for jsonl_file in self.sessions_dir.glob("*.jsonl"):
            is_agent = jsonl_file.name.startswith("agent-")

            if not include_agent_sessions and is_agent:
                continue

            # Extract session ID from filename
            session_id = jsonl_file.stem  # Remove .jsonl extension

            # Try to read basic metadata without loading full session
            try:
                metadata = self._read_session_metadata(jsonl_file)
                sessions.append(
                    {
                        "session_id": session_id,
                        "file_path": str(jsonl_file),
                        "is_agent_session": is_agent,
                        "created_at": (
                            metadata["created_at"].isoformat()
                            if metadata.get("created_at")
                            else None
                        ),
                        "last_activity": (
                            metadata["last_activity"].isoformat()
                            if metadata.get("last_activity")
                            else None
                        ),
                        "message_count": metadata.get("message_count", 0),
                        "summary": metadata.get("summary"),
                    }
                )
            except Exception as e:
                logger.warning("Failed to read session %s: %s", session_id, e)
                continue

        # Sort by last activity (newest first), tie-breaker by session_id (desc)
        sessions.sort(
            key=lambda s: (s["last_activity"] or "", s["session_id"]),
            reverse=True,
        )

        return sessions

    def get_session(self, session_id: str) -> ClaudeSession | None:
        """
        Load a complete session with all messages.

        Args:
            session_id: Session UUID or agent ID

        Returns:
            ClaudeSession object or None if not found
        """
        jsonl_file = self.sessions_dir / f"{session_id}.jsonl"
        if not jsonl_file.exists():
            logger.warning("Session file not found: %s", jsonl_file)
            return None

        try:
            return self._read_session(jsonl_file)
        except Exception:
            logger.exception("Failed to read session %s", session_id)
            return None

    def _read_session_metadata(self, jsonl_file: Path) -> dict[str, Any]:
        """
        Read minimal session metadata without loading all messages.

        Args:
            jsonl_file: Path to JSONL session file

        Returns:
            Dictionary with metadata
        """
        metadata: dict[str, Any] = {
            "created_at": None,
            "last_activity": None,
            "message_count": 0,
            "summary": None,
        }

        with jsonl_file.open("r", encoding="utf-8") as f:
            for line_num, raw_line in enumerate(f):
                line = raw_line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                    msg_type = data.get("type")

                    # Extract summary from first line if present
                    if line_num == 0 and msg_type == "summary":
                        metadata["summary"] = data.get("summary")
                        continue

                    # Track message timestamps
                    if msg_type in ("user", "assistant"):
                        timestamp_str = data.get("timestamp")
                        if timestamp_str:
                            timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))

                            if metadata["created_at"] is None:
                                metadata["created_at"] = timestamp
                            metadata["last_activity"] = timestamp
                            metadata["message_count"] += 1

                except json.JSONDecodeError:
                    logger.warning(
                        "Invalid JSON in %s line %d",
                        jsonl_file.name,
                        line_num + 1,
                    )
                    continue

        return metadata

    def _read_session(self, jsonl_file: Path) -> ClaudeSession:
        """
        Read complete session from JSONL file.

        Args:
            jsonl_file: Path to JSONL session file

        Returns:
            ClaudeSession object
        """
        session_id = jsonl_file.stem
        is_agent = jsonl_file.name.startswith("agent-")
        agent_id = session_id.replace("agent-", "") if is_agent else None

        session = ClaudeSession(
            session_id=session_id,
            file_path=jsonl_file,
            is_agent_session=is_agent,
            agent_id=agent_id,
        )

        with jsonl_file.open("r", encoding="utf-8") as f:
            for line_num, raw_line in enumerate(f):
                line = raw_line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                    msg_type = data.get("type")

                    # Handle summary line (usually first line)
                    if msg_type == "summary":
                        session.summary = data.get("summary")
                        continue

                    # Skip non-message lines
                    if msg_type not in (
                        "user",
                        "assistant",
                        "file-history-snapshot",
                    ):
                        continue

                    # Parse message
                    timestamp_str = data.get("timestamp")
                    timestamp = (
                        datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                        if timestamp_str
                        else datetime.now()
                    )

                    message = ClaudeMessage(
                        uuid=data.get("uuid", ""),
                        parent_uuid=data.get("parentUuid"),
                        timestamp=timestamp,
                        type=msg_type,
                        message=data.get("message"),
                        is_sidechain=data.get("isSidechain", False),
                        agent_id=data.get("agentId"),
                    )

                    session.messages.append(message)

                except json.JSONDecodeError:
                    logger.warning(
                        "Invalid JSON in %s line %d",
                        jsonl_file.name,
                        line_num + 1,
                    )
                    continue
                except Exception as e:
                    logger.warning(
                        "Error parsing line %d in %s: %s",
                        line_num + 1,
                        jsonl_file.name,
                        e,
                    )
                    continue

        return session
