"""Chat endpoints for streaming agent interactions."""

import asyncio
import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Query, WebSocket, status
from fastapi.websockets import WebSocketDisconnect

from app.dependencies import get_agent_session_manager, get_chat_session_manager
from app.models.chat import (
    ChatHistoryResponse,
    ChatMessage,
    ChatSessionResponse,
    WSInputMessage,
    WSMessageType,
)
from app.services.chat_session_manager import ChatSessionManager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])


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

    def disconnect(self, connection_id: str) -> None:
        """
        Clean up connection.

        Args:
            connection_id: Connection identifier
        """
        self.active_connections.pop(connection_id, None)
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
        websocket = self.active_connections.get(connection_id)
        if not websocket:
            return False

        try:
            await websocket.send_json(message)
            return True
        except Exception as e:
            logger.error("Error sending to connection %s: %s", connection_id, e)
            self.disconnect(connection_id)
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
    # Validate session exists
    if not session_manager.session_exists(session_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    # Load messages from Claude Code session
    messages = session_manager.get_session_messages(
        session_id,
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

    logger.info("Retrieved %d messages for Claude session %s", len(chat_messages), session_id)

    return ChatHistoryResponse(
        session_id=session_id,
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

        Server → Client:
            {"type": "connected", "connection_id": "conn_xxx", "session_id": "uuid"}
            {"type": "session_id", "session_id": "uuid"}  # Sent when session ID is captured
            {"type": "text", "chunk": "..."}
            {"type": "tool_use", "name": "Read", "input": {...}}
            {"type": "thinking", "content": "..."}
            {"type": "complete", "status": "success", "cost_usd": 0.01, ...}
            {"type": "error", "error": "..."}
            {"type": "session_taken"}  # Sent when another client takes over

    Args:
        websocket: WebSocket connection
        session_id: Session identifier (Claude UUID, "new", or connection ID)
        session_manager: ChatSessionManager for managing sessions
        agent_session_manager: AgentSessionManager for managing agent sessions
    """
    # Determine if this is a resume or new session
    claude_session_id = None

    if session_id != "new" and not session_id.startswith("conn_"):
        # Validate Claude session exists
        if session_manager.session_exists(session_id):
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
        await websocket.send_json(
            {
                "type": WSMessageType.CONNECTED.value,
                "connection_id": connection_id,
                "session_id": agent_session.session_id,
            }
        )

        # Replay buffered messages
        for msg in buffered:
            await websocket.send_json(msg)

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
                    await agent_session_manager.send_user_message(
                        agent_session.session_id, user_message
                    )

                elif msg.type == WSMessageType.INTERRUPT:
                    # TODO: Implement interrupt support
                    await websocket.send_json(
                        {
                            "type": WSMessageType.ERROR.value,
                            "error": "Interrupt not yet implemented",
                        }
                    )

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
        connection_manager.disconnect(connection_id)
