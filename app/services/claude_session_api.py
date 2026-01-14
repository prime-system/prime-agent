"""API service for Claude Code sessions."""

import logging
from pathlib import Path
from typing import Any

from app.services.claude_session_reader import ClaudeMessage, ClaudeSession, ClaudeSessionReader

logger = logging.getLogger(__name__)


class ClaudeSessionAPI:
    """High-level API for accessing Claude Code sessions."""

    def __init__(
        self,
        project_path: str | Path,
        claude_home: str | Path = "/home/prime/.claude",
    ):
        """
        Initialize session API.

        Args:
            project_path: Absolute path to project directory
            claude_home: Path to Claude Code home directory
        """
        self.reader = ClaudeSessionReader(project_path, claude_home)

    def list_sessions(
        self,
        include_agent_sessions: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        List available sessions with metadata.

        Args:
            include_agent_sessions: Whether to include agent/sidechain sessions
            limit: Maximum number of sessions to return (None for all)

        Returns:
            List of session metadata dictionaries
        """
        sessions = self.reader.list_sessions(include_agent_sessions=include_agent_sessions)

        if limit is not None:
            sessions = sessions[:limit]

        return sessions

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """
        Get complete session data.

        Args:
            session_id: Session UUID or agent ID

        Returns:
            Session dictionary with messages, or None if not found
        """
        session = self.reader.get_session(session_id)
        if not session:
            return None

        return self._session_to_dict(session)

    def get_session_messages(
        self,
        session_id: str,
        roles: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get messages from a session, optionally filtered by role.

        Args:
            session_id: Session UUID or agent ID
            roles: Optional list of roles to include (e.g., ["user", "assistant"])

        Returns:
            List of message dictionaries
        """
        session = self.reader.get_session(session_id)
        if not session:
            return []

        messages = []
        for msg in session.messages:
            # Skip non-message types
            if msg.type not in ("user", "assistant"):
                continue

            # Filter by role if specified
            if roles and msg.role not in roles:
                continue

            messages.append(self._message_to_dict(msg))

        return messages

    def get_session_summary(self, session_id: str) -> dict[str, Any] | None:
        """
        Get session metadata without loading all messages.

        Args:
            session_id: Session UUID or agent ID

        Returns:
            Session metadata dictionary or None if not found
        """
        sessions = self.reader.list_sessions(include_agent_sessions=True)
        for session in sessions:
            if session["session_id"] == session_id:
                return session
        return None

    def search_sessions(
        self,
        query: str | None = None,
        include_agent_sessions: bool = False,
        limit: int | None = 50,
    ) -> list[dict[str, Any]]:
        """
        Search sessions by summary or content.

        Args:
            query: Search query (searches in summary)
            include_agent_sessions: Whether to include agent sessions
            limit: Maximum number of results (None for all)

        Returns:
            List of matching session metadata
        """
        sessions = self.list_sessions(
            include_agent_sessions=include_agent_sessions,
            limit=None,
        )

        if query:
            query_lower = query.lower()
            sessions = [
                s for s in sessions if s.get("summary") and query_lower in s["summary"].lower()
            ]

        return sessions[:limit]

    def _session_to_dict(self, session: ClaudeSession) -> dict[str, Any]:
        """Convert ClaudeSession to dictionary format."""
        return {
            "session_id": session.session_id,
            "summary": session.summary,
            "is_agent_session": session.is_agent_session,
            "agent_id": session.agent_id,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "last_activity": (session.last_activity.isoformat() if session.last_activity else None),
            "message_count": session.message_count,
            "messages": [self._message_to_dict(msg) for msg in session.messages],
        }

    def _message_to_dict(self, message: ClaudeMessage) -> dict[str, Any]:
        """Convert ClaudeMessage to dictionary format."""
        result = {
            "uuid": message.uuid,
            "parent_uuid": message.parent_uuid,
            "timestamp": message.timestamp.isoformat(),
            "type": message.type,
            "role": message.role,
            "content": message.content,
            "is_sidechain": message.is_sidechain,
            "agent_id": message.agent_id,
        }

        # Extract tool metadata from message content if present
        if message.message and isinstance(message.message.get("content"), list):
            for block in message.message["content"]:
                if block.get("type") == "tool_use":
                    result["tool_name"] = block.get("name")
                    result["tool_input"] = block.get("input")
                    break

        return result
