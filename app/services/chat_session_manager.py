"""Chat session manager working directly with Claude Code sessions."""

import logging
from pathlib import Path
from typing import Any

from app.services.claude_session_api import ClaudeSessionAPI

logger = logging.getLogger(__name__)


class ChatSessionManager:
    """
    Manages chat sessions using Claude Code's native session system.

    This is a thin wrapper around ClaudeSessionAPI that provides
    session management for the chat API without creating a separate
    Prime session layer.

    All session IDs are Claude Code session UUIDs.
    All messages are stored in Claude Code JSONL files.
    No separate .sessions/ folder is used.
    """

    def __init__(
        self,
        vault_path: str,
        claude_home: str = "/home/prime/.claude",
    ) -> None:
        """
        Initialize chat session manager.

        Args:
            vault_path: Path to vault directory (used as project path)
            claude_home: Path to Claude Code home directory
        """
        self.vault_path = Path(vault_path)
        self.claude_api = ClaudeSessionAPI(
            project_path=vault_path,
            claude_home=claude_home,
        )

    def session_exists(self, session_id: str) -> bool:
        """
        Check if a Claude Code session exists.

        Args:
            session_id: Claude Code session UUID

        Returns:
            True if session exists, False otherwise
        """
        try:
            # Try to get session summary to check if it exists
            summary = self.claude_api.get_session_summary(session_id)
            return summary is not None
        except Exception:
            return False

    def get_session_messages(
        self,
        session_id: str,
        roles: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get messages from Claude Code session.

        Args:
            session_id: Claude Code session UUID
            roles: Optional list of roles to filter (e.g., ["user", "assistant"])

        Returns:
            List of message dictionaries with role, content, timestamp
        """
        return self.claude_api.get_session_messages(session_id, roles=roles)

    def get_session_metadata(self, session_id: str) -> dict[str, Any] | None:
        """
        Get metadata for Claude Code session.

        Args:
            session_id: Claude Code session UUID

        Returns:
            Metadata dictionary
        """
        return self.claude_api.get_session_summary(session_id)

    def list_sessions(self) -> list[dict[str, Any]]:
        """
        List all Claude Code sessions for this project.

        Returns:
            List of session metadata dictionaries
        """
        return self.claude_api.list_sessions()
