"""Chat session and message models for streaming agent interactions."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ChatSessionResponse(BaseModel):
    """Response for creating a chat session."""

    session_id: str = Field(..., description="Unique session identifier")
    created_at: datetime = Field(..., description="Session creation timestamp")


class SendMessageRequest(BaseModel):
    """Request to send a message to chat session."""

    message: str = Field(..., min_length=1, description="User message content")


class SendMessageResponse(BaseModel):
    """Response after queuing a message."""

    status: str = Field(default="queued", description="Message status")
    message_id: str = Field(..., description="Unique message identifier")


class ChatMessage(BaseModel):
    """Single chat message."""

    role: str = Field(..., description="Message role: user or assistant")
    content: str = Field(..., description="Message content")
    timestamp: datetime = Field(..., description="Message timestamp")
    tool_name: str | None = Field(None, description="Tool name if this is a tool call")
    tool_input: dict[str, Any] | None = Field(None, description="Tool input parameters")


class ChatHistoryResponse(BaseModel):
    """Response containing session message history."""

    session_id: str = Field(..., description="Session identifier")
    messages: list[ChatMessage] = Field(default_factory=list, description="Message history")
    message_count: int = Field(..., description="Total message count")


class SSEEventType(str, Enum):
    """Types of SSE events emitted by stream endpoint."""

    TEXT = "text"
    TOOL_USE = "tool_use"
    THINKING = "thinking"
    COMPLETE = "complete"
    ERROR = "error"


class SSEEvent(BaseModel):
    """SSE event data structure."""

    type: SSEEventType = Field(..., description="Event type")
    data: dict = Field(default_factory=dict, description="Event payload")


class WSMessageType(str, Enum):
    """WebSocket message types for bidirectional communication."""

    # Client → Server
    USER_MESSAGE = "user_message"
    INTERRUPT = "interrupt"

    # Server → Client
    CONNECTED = "connected"
    SESSION_TAKEN = "session_taken"
    TEXT = "text"
    TOOL_USE = "tool_use"
    THINKING = "thinking"
    COMPLETE = "complete"
    ERROR = "error"


class WSInputMessage(BaseModel):
    """Client-to-server WebSocket message."""

    type: WSMessageType = Field(..., description="Message type")
    data: dict[str, Any] = Field(default_factory=dict, description="Message payload")


class WSOutputMessage(BaseModel):
    """
    Server-to-client WebSocket message.

    Fields vary by message type. Only relevant fields should be populated.
    """

    type: WSMessageType = Field(..., description="Message type")

    # Fields for specific message types
    session_id: str | None = Field(None, description="Session ID (for CONNECTED)")
    chunk: str | None = Field(None, description="Text chunk (for TEXT)")
    name: str | None = Field(None, description="Tool name (for TOOL_USE)")
    input: dict[str, Any] | None = Field(None, description="Tool input (for TOOL_USE)")
    content: str | None = Field(None, description="Thinking content (for THINKING)")
    status: str | None = Field(None, description="Status (for COMPLETE)")
    cost_usd: float | None = Field(None, description="Cost in USD (for COMPLETE)")
    duration_ms: int | None = Field(None, description="Duration in ms (for COMPLETE)")
    error: str | None = Field(None, description="Error message (for ERROR)")
