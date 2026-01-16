"""Chat session and message models for streaming agent interactions."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
    data: dict[str, Any] = Field(default_factory=dict, description="Event payload")


class WSMessageType(str, Enum):
    """WebSocket message types for bidirectional communication."""

    # Client → Server
    USER_MESSAGE = "user_message"
    INTERRUPT = "interrupt"
    ASK_USER_RESPONSE = "ask_user_response"

    # Server → Client
    CONNECTED = "connected"
    SESSION_ID = "session_id"
    SESSION_TAKEN = "session_taken"
    SESSION_STATUS = "session_status"
    ASK_USER_QUESTION = "ask_user_question"
    ASK_USER_TIMEOUT = "ask_user_timeout"
    TEXT = "text"
    TOOL_USE = "tool_use"
    THINKING = "thinking"
    COMPLETE = "complete"
    ERROR = "error"


class WSInputMessage(BaseModel):
    """Client-to-server WebSocket message."""

    type: WSMessageType = Field(..., description="Message type")
    data: dict[str, Any] = Field(default_factory=dict, description="Message payload")


class AskUserResponseData(BaseModel):
    """AskUserQuestion response payload from client."""

    model_config = ConfigDict(populate_by_name=True)

    question_id: str = Field(..., alias="questionId", description="Question ID to answer")
    answers: dict[str, str | list[str]] = Field(
        default_factory=dict,
        description="Question answers keyed by question text",
    )
    cancelled: bool = Field(default=False, description="Whether the user cancelled the prompt")


class WSOutputMessage(BaseModel):
    """
    Server-to-client WebSocket message.

    Fields vary by message type. Only relevant fields should be populated.
    """

    model_config = ConfigDict(populate_by_name=True)

    type: WSMessageType = Field(..., description="Message type")

    # Fields for specific message types
    session_id: str | None = Field(
        None,
        alias="sessionId",
        description="Session ID (camelCase preferred; snake_case accepted)",
    )
    connection_id: str | None = Field(
        None,
        alias="connectionId",
        description="Connection ID (camelCase preferred; snake_case accepted)",
    )
    chunk: str | None = Field(None, description="Text chunk (for TEXT)")
    name: str | None = Field(None, description="Tool name (for TOOL_USE)")
    input: dict[str, Any] | None = Field(None, description="Tool input (for TOOL_USE)")
    content: str | None = Field(None, description="Thinking content (for THINKING)")
    status: str | None = Field(
        None,
        description="Status (for COMPLETE or SESSION_STATUS)",
    )
    question_id: str | None = Field(
        None,
        alias="questionId",
        description="Question ID (for ASK_USER_QUESTION)",
    )
    questions: list[dict[str, Any]] | None = Field(
        None,
        description="AskUserQuestion prompts (for ASK_USER_QUESTION)",
    )
    timeout_seconds: int | None = Field(
        None,
        description="Timeout in seconds (for ASK_USER_QUESTION)",
    )
    cost_usd: float | None = Field(
        None,
        alias="costUsd",
        description="Cost in USD (camelCase preferred; snake_case accepted)",
    )
    duration_ms: int | None = Field(
        None,
        alias="durationMs",
        description="Duration in ms (camelCase preferred; snake_case accepted)",
    )
    error: str | None = Field(None, description="Error message (for ERROR)")
    is_permanent: bool | None = Field(
        None,
        alias="isPermanent",
        description="Whether error is permanent (for ERROR)",
    )
    is_processing: bool | None = Field(
        None,
        description="Whether the session is currently processing (for SESSION_STATUS)",
    )
    waiting_for_user: bool | None = Field(
        None,
        description="Whether the session is awaiting AskUserQuestion response (for SESSION_STATUS)",
    )
    pending_question_id: str | None = Field(
        None,
        alias="pendingQuestionId",
        description="Pending AskUserQuestion ID (for SESSION_STATUS)",
    )
    last_event_type: str | None = Field(
        None,
        description="Last event type emitted for this session (for SESSION_STATUS)",
    )
    buffered_count: int | None = Field(
        None,
        description="Number of buffered events pending replay (for SESSION_STATUS)",
    )
    last_activity: str | None = Field(
        None,
        description="ISO timestamp of last activity (for SESSION_STATUS)",
    )
    completed_at: str | None = Field(
        None,
        description="ISO timestamp when the session completed (for SESSION_STATUS)",
    )
