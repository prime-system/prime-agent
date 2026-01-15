"""Chat endpoints for streaming agent interactions."""

import asyncio
import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Query, WebSocket, status
from fastapi.websockets import WebSocketDisconnect

from app.dependencies import get_agent_session_manager, get_chat_session_manager
from app.models.chat import (
    AskUserResponseData,
    ChatHistoryResponse,
    ChatMessage,
    ChatSessionResponse,
    WSInputMessage,
    WSMessageType,
)
from app.services.chat_session_manager import ChatSessionManager
from app.utils.path_validation import PathValidationError, validate_session_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


class ConnectionManager:
    """
    Simplified WebSocket connection manager.

    Session lifecycle is now handled by AgentSessionManager.
    This class only manages WebSocket connections.
    """

    def __init__(self) -> None:
        """Initialize connection manager."""
        self.active_connections: dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def connect(self, connection_id: str, websocket: WebSocket) -> bool:
        """
        Accept WebSocket connection.

        Args:
            connection_id: Connection identifier
            websocket: WebSocket connection

        Returns:
            True if connected successfully, False if already connected
        """
        async with self._lock:
            if connection_id in self.active_connections:
                await websocket.close(code=1008, reason="Connection already active")
                logger.warning("Rejected duplicate connection %s", connection_id)
                return False

            await websocket.accept()
            self.active_connections[connection_id] = websocket

            logger.info("WebSocket connected (connection=%s)", connection_id)
            return True

    async def disconnect(
        self,
        connection_id: str,
        *,
        code: int = 1000,
        reason: str | None = None,
    ) -> None:
        """
        Clean up connection.

        Args:
            connection_id: Connection identifier
        """
        async with self._lock:
            websocket = self.active_connections.pop(connection_id, None)

        if not websocket:
            return

        try:
            await websocket.close(code=code, reason=reason or "")
        except Exception as e:
            logger.debug("Error closing WebSocket %s: %s", connection_id, e)

        logger.info("WebSocket disconnected (connection=%s)", connection_id)

    async def send_message(self, connection_id: str, message: dict[str, Any]) -> bool:
        """
        Send message to connected client.

        Args:
            connection_id: Connection identifier
            message: Message dictionary to send

        Returns:
            True if sent successfully, False if connection doesn't exist
        """
        async with self._lock:
            websocket = self.active_connections.get(connection_id)
        if not websocket:
            return False

        try:
            await websocket.send_json(message)
            return True
        except Exception as e:
            logger.error("Error sending to connection %s: %s", connection_id, e)
            await self.disconnect(connection_id)
            return False


# Module-level connection manager
connection_manager = ConnectionManager()


@router.post("/sessions", response_model=ChatSessionResponse)
async def create_session(
    user_id: str | None = Query(None),
) -> ChatSessionResponse:
    """
    Create a new chat session placeholder.

    Note: The actual Claude session is created on the first message
    sent via WebSocket. This endpoint just returns a connection ID
    that the client can use to connect.

    Args:
        user_id: Optional user identifier (ignored)

    Returns:
        Session metadata with connection_id
    """
    from datetime import UTC, datetime

    connection_id = f"conn_{uuid4().hex[:16]}"

    return ChatSessionResponse(
        session_id=connection_id,
        created_at=datetime.now(UTC),
    )


@router.get(
    "/sessions/{session_id}/messages",
    response_model=ChatHistoryResponse,
)
async def get_session_messages(
    session_id: str = Path(..., description="Claude session ID to retrieve messages from"),
    session_manager: ChatSessionManager = Depends(get_chat_session_manager),
) -> ChatHistoryResponse:
    """
    Retrieve message history for a Claude Code session.

    Returns all messages stored in the Claude session, ordered chronologically.
    Used by clients to restore conversation history when switching sessions.

    Args:
        session_id: Claude Code session UUID

    Returns:
        Message history with session metadata

    Raises:
        HTTPException: If session not found (404)
    """
    # Validate session_id format to prevent path traversal
    try:
        validated_id = validate_session_id(session_id)
    except PathValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid session ID: {e}",
        )

    # Validate session exists
    if not session_manager.session_exists(validated_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {validated_id} not found",
        )

    # Load messages from Claude Code session
    messages = session_manager.get_session_messages(
        validated_id,
        roles=["user", "assistant"],
    )

    # Convert messages to response format, filtering out empty content
    # Keep messages that have text content OR tool metadata
    chat_messages = [
        ChatMessage(
            role=msg["role"],
            content=msg["content"],
            timestamp=msg["timestamp"],
            tool_name=msg.get("tool_name"),
            tool_input=msg.get("tool_input"),
        )
        for msg in messages
        if (msg["content"] and msg["content"].strip()) or msg.get("tool_name")
    ]

    logger.info("Retrieved %d messages for Claude session %s", len(chat_messages), validated_id)

    return ChatHistoryResponse(
        session_id=validated_id,
        messages=chat_messages,
        message_count=len(chat_messages),
    )


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    session_manager: ChatSessionManager = Depends(get_chat_session_manager),
    agent_session_manager: Any = Depends(get_agent_session_manager),
) -> None:
    """
    WebSocket endpoint for bidirectional chat communication.

    Session ID can be:
    - A Claude session UUID to resume an existing session
    - "new" to start a new session
    - A connection ID from create_session endpoint

    Protocol:
        Client → Server:
            {"type": "user_message", "data": {"message": "text"}}
            {"type": "interrupt"}
            {"type": "ask_user_response", "data": {"question_id": "q_123", "answers": {...}}}

        Server → Client:
            {"type": "connected", "connectionId": "conn_xxx", "sessionId": "uuid"}
            {"type": "session_id", "sessionId": "uuid"}  # Sent when session ID is captured
            {"type": "text", "chunk": "..."}
            {"type": "tool_use", "name": "Read", "input": {...}}
            {"type": "thinking", "content": "..."}
            {"type": "ask_user_question", "question_id": "q_123", "questions": [...], "timeout_seconds": 55}
            {"type": "ask_user_timeout", "question_id": "q_123", "error": "..."}
            {"type": "complete", "status": "success", "costUsd": 0.01, "durationMs": 1200}
            {"type": "error", "error": "...", "isPermanent": true}
            {"type": "session_taken"}  # Sent when another client takes over
            {"type": "session_status", "session_id": "uuid", "is_processing": false, ...}

    Args:
        websocket: WebSocket connection
        session_id: Session identifier (Claude UUID, "new", or connection ID)
        session_manager: ChatSessionManager for managing sessions
        agent_session_manager: AgentSessionManager for managing agent sessions
    """
    # Determine if this is a resume or new session
    claude_session_id = None

    if session_id != "new" and not session_id.startswith("conn_"):
        # Validate Claude session exists on disk or in memory
        if session_manager.session_exists(session_id) or agent_session_manager.has_session(
            session_id
        ):
            claude_session_id = session_id
            logger.info("Will resume Claude session %s", claude_session_id)
        else:
            await websocket.close(code=1008, reason="Session not found")
            logger.warning("WebSocket connection rejected: Claude session %s not found", session_id)
            return

    # Generate connection ID
    connection_id = f"conn_{uuid4().hex[:16]}"

    # Connect WebSocket
    connected = await connection_manager.connect(connection_id, websocket)
    if not connected:
        return  # Already connected elsewhere

    agent_session = None

    try:
        # Get or create agent session
        agent_session = await agent_session_manager.get_or_create_session(claude_session_id)

        # Attach WebSocket and replay buffer
        buffered = await agent_session_manager.attach_websocket(
            agent_session.session_id, connection_id, connection_manager
        )

        # Send connection confirmation
        connected_payload: dict[str, Any] = {
            "type": WSMessageType.CONNECTED.value,
            "connection_id": connection_id,
            "connectionId": connection_id,
        }
        if not agent_session.session_id.startswith("pending_"):
            connected_payload["session_id"] = agent_session.session_id
            connected_payload["sessionId"] = agent_session.session_id

        await websocket.send_json(connected_payload)

        async with agent_session.ws_lock:
            last_activity = agent_session.last_activity
            completed_at = agent_session.completed_at
            last_event_type = agent_session.last_event_type
            is_processing = agent_session.is_processing
            waiting_for_user = agent_session.waiting_for_user
            pending_question_id = agent_session.pending_question_id

        session_status_payload: dict[str, Any] = {
            "type": WSMessageType.SESSION_STATUS.value,
            "session_id": agent_session.session_id,
            "is_processing": is_processing,
            "waiting_for_user": waiting_for_user,
            "pending_question_id": pending_question_id,
            "last_event_type": last_event_type,
            "buffered_count": len(buffered),
            "last_activity": last_activity.isoformat() if last_activity else None,
            "completed_at": completed_at.isoformat() if completed_at else None,
        }
        await websocket.send_json(session_status_payload)

        # Replay buffered messages
        for msg in buffered:
            await websocket.send_json(msg)
        await agent_session_manager.finish_replay(agent_session, connection_id, connection_manager)

        # Listen for incoming messages
        while True:
            # Receive message from client
            data = await websocket.receive_json()

            # Parse message
            try:
                msg = WSInputMessage(**data)

                if msg.type == WSMessageType.USER_MESSAGE:
                    user_message = msg.data.get("message")
                    if not user_message:
                        await websocket.send_json(
                            {
                                "type": WSMessageType.ERROR.value,
                                "error": "Missing 'message' field in data",
                            }
                        )
                        continue

                    # Send to agent session
                    accepted = await agent_session_manager.send_user_message(
                        agent_session.session_id,
                        user_message,
                        ws_id=connection_id,
                        connection_manager=connection_manager,
                    )
                    if not accepted:
                        break

                elif msg.type == WSMessageType.INTERRUPT:
                    # TODO: Implement interrupt support
                    await websocket.send_json(
                        {
                            "type": WSMessageType.ERROR.value,
                            "error": "Interrupt not yet implemented",
                        }
                    )

                elif msg.type == WSMessageType.ASK_USER_RESPONSE:
                    try:
                        response_data = AskUserResponseData(**msg.data)
                    except Exception as e:
                        await websocket.send_json(
                            {
                                "type": WSMessageType.ERROR.value,
                                "error": f"Invalid ask_user_response: {e}",
                            }
                        )
                        continue

                    outcome, error_message = await agent_session_manager.submit_ask_user_response(
                        agent_session.session_id,
                        response_data.question_id,
                        response_data.answers,
                        cancelled=response_data.cancelled,
                        ws_id=connection_id,
                        connection_manager=connection_manager,
                    )

                    if outcome == "session_taken":
                        break
                    if outcome == "invalid":
                        await websocket.send_json(
                            {
                                "type": WSMessageType.ERROR.value,
                                "error": error_message or "Invalid ask_user_response",
                            }
                        )
                    # ignored/accepted require no immediate response

            except Exception as e:
                logger.error("Error handling message: %s", e)
                await websocket.send_json(
                    {
                        "type": WSMessageType.ERROR.value,
                        "error": f"Invalid message format: {e}",
                    }
                )

    except WebSocketDisconnect:
        logger.info("Client disconnected from connection %s", connection_id)
    except Exception as e:
        logger.exception("WebSocket error for connection %s: %s", connection_id, e)
    finally:
        # Detach from agent session (if initialized)
        if agent_session:
            await agent_session_manager.detach_websocket(agent_session.session_id, connection_id)
        # Cleanup connection
        await connection_manager.disconnect(connection_id)
