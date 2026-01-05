"""Session and message models for chat interactions."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SessionStatus(str, Enum):
    """Session status states."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


@dataclass
class Message:
    """Represents a single message in conversation history."""

    role: str
    content: str
    timestamp: datetime

    def to_dict(self) -> dict[str, str]:
        """Convert message to dictionary format."""
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        """Create Message from dictionary."""
        timestamp = data["timestamp"]
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        return cls(
            role=data["role"],
            content=data["content"],
            timestamp=timestamp,
        )


@dataclass
class Session:
    """Represents a chat session with conversational state."""

    session_id: str
    user_id: str
    created_at: datetime
    last_activity: datetime
    status: str = SessionStatus.ACTIVE.value
    message_count: int = 0
    messages: list[Message] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    agent_session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert session to dictionary format for persistence."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "status": self.status,
            "message_count": self.message_count,
            "messages": [msg.to_dict() for msg in self.messages],
            "config": self.config,
            "agent_session_id": self.agent_session_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Session":
        """Create Session from dictionary format."""
        messages = [Message.from_dict(msg) for msg in data.get("messages", [])]
        created_at = data["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        last_activity = data["last_activity"]
        if isinstance(last_activity, str):
            last_activity = datetime.fromisoformat(last_activity)

        return cls(
            session_id=data["session_id"],
            user_id=data["user_id"],
            created_at=created_at,
            last_activity=last_activity,
            status=data.get("status", SessionStatus.ACTIVE.value),
            message_count=data.get("message_count", 0),
            messages=messages,
            config=data.get("config", {}),
            agent_session_id=data.get("agent_session_id"),
        )
