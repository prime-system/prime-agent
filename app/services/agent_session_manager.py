"""
Agent Session Manager for persistent, WebSocket-independent sessions.

This module decouples Agent session lifecycle from WebSocket connections,
enabling sessions to persist across reconnections.
"""

import asyncio
import functools
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from claude_agent_sdk import ClaudeSDKClient

from app.services.agent_chat import AgentChatService

logger = logging.getLogger(__name__)


@dataclass
class AgentSessionState:
    """State for a long-lived agent session."""

    session_id: str
    client: ClaudeSDKClient
    processing_task: asyncio.Task[None]
    input_queue: asyncio.Queue[str]
    message_buffer: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=100))
    last_activity: datetime = field(default_factory=lambda: datetime.now(UTC))
    connected_ws_id: str | None = None
    is_processing: bool = False


class AgentSessionManager:
    """
    Manages long-lived agent sessions independent of WebSocket connections.

    Features:
    - Sessions persist across WebSocket disconnects
    - Message buffering during disconnection
    - 30-minute timeout for inactive sessions
    - Exclusive connections (one client at a time)
    - Early termination when response completes with no connected client
    """

    TIMEOUT_SECONDS = 1800  # 30 minutes
    GRACE_PERIOD_SECONDS = 5  # After completion, wait before termination

    def __init__(self, agent_service: AgentChatService):
        """
        Initialize agent session manager.

        Args:
            agent_service: AgentChatService for creating SDK clients
        """
        self.agent_service = agent_service
        self.sessions: dict[str, AgentSessionState] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task[None] | None = None

    async def get_or_create_session(self, session_id: str | None) -> AgentSessionState:
        """
        Get existing session or create new one.

        Args:
            session_id: Optional Claude session ID to resume

        Returns:
            AgentSessionState for the session
        """
        async with self._lock:
            # Check if session already exists (for resume)
            if session_id and session_id in self.sessions:
                state = self.sessions[session_id]
                state.last_activity = datetime.now(UTC)
                logger.info("Resuming existing agent session %s", session_id)
                return state

            # Create new session
            logger.info("Creating new agent session (resume=%s)", session_id)

            # Create long-lived ClaudeSDKClient
            client = self.agent_service.create_client_instance(session_id=session_id)

            # Create state
            input_queue: asyncio.Queue[str] = asyncio.Queue()
            processing_task = asyncio.create_task(
                self._process_session_loop(session_id or "new", input_queue, client)
            )

            # Will be updated with actual session_id once client is initialized
            temp_session_id = session_id or "new"
            temp_state = AgentSessionState(
                session_id=temp_session_id,
                client=client,
                processing_task=processing_task,
                input_queue=input_queue,
            )

            # Always add to sessions dict (will be moved to actual ID later)
            self.sessions[temp_session_id] = temp_state

            return temp_state

    async def attach_websocket(
        self,
        session_id: str,
        ws_id: str,
        connection_manager: Any,
    ) -> list[dict[str, Any]]:
        """
        Attach WebSocket to session, kicking previous client if exists.

        Args:
            session_id: Agent session ID
            ws_id: WebSocket connection ID
            connection_manager: ConnectionManager instance for sending messages

        Returns:
            List of buffered messages to replay
        """
        async with self._lock:
            state = self.sessions.get(session_id)
            if not state:
                logger.error("Cannot attach to non-existent session %s", session_id)
                return []

            # Kick previous client if exists
            if state.connected_ws_id and state.connected_ws_id != ws_id:
                logger.info(
                    "Kicking previous client %s (new client: %s)",
                    state.connected_ws_id,
                    ws_id,
                )
                await connection_manager.send_message(
                    state.connected_ws_id,
                    {"type": "session_taken"},
                )
                connection_manager.disconnect(state.connected_ws_id)

            # Attach new client
            state.connected_ws_id = ws_id
            state.last_activity = datetime.now(UTC)

            # Drain and return buffered messages
            buffered = list(state.message_buffer)
            state.message_buffer.clear()

            logger.info(
                "Attached WebSocket %s to session %s (buffered: %d)",
                ws_id,
                session_id,
                len(buffered),
            )
            return buffered

    async def detach_websocket(self, session_id: str, ws_id: str) -> None:
        """
        Detach WebSocket from session.

        Session continues in background, buffering messages.

        Args:
            session_id: Agent session ID
            ws_id: WebSocket connection ID to detach
        """
        async with self._lock:
            state = self.sessions.get(session_id)
            if not state:
                return

            # Only detach if this is the currently attached client
            if state.connected_ws_id == ws_id:
                state.connected_ws_id = None
                logger.info("Detached WebSocket %s from session %s", ws_id, session_id)

    async def send_user_message(self, session_id: str, message: str) -> None:
        """
        Queue user message for processing.

        Args:
            session_id: Agent session ID
            message: User message content
        """
        state = self.sessions.get(session_id)
        if not state:
            logger.error("Cannot send message to non-existent session %s", session_id)
            return

        await state.input_queue.put(message)
        state.last_activity = datetime.now(UTC)
        logger.debug("Queued message for session %s", session_id)

    async def terminate_session(self, session_id: str) -> None:
        """
        Terminate session and cleanup resources.

        Args:
            session_id: Agent session ID to terminate
        """
        async with self._lock:
            state = self.sessions.pop(session_id, None)
            if not state:
                return

            # Cancel processing task
            if not state.processing_task.done():
                state.processing_task.cancel()
                try:
                    await state.processing_task
                except asyncio.CancelledError:
                    pass

            # Close SDK client
            try:
                await state.client.__aexit__(None, None, None)
            except Exception as e:
                logger.warning("Error closing SDK client for %s: %s", session_id, e)

            logger.info("Terminated session %s", session_id)

    def start_cleanup_loop(self) -> None:
        """Start background task to cleanup inactive sessions."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("Started session cleanup loop")

    async def stop_cleanup_loop(self) -> None:
        """Stop cleanup loop."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            logger.info("Stopped session cleanup loop")

    async def terminate_all_sessions(self) -> None:
        """Terminate all active sessions (used during shutdown)."""
        session_ids = list(self.sessions.keys())
        for session_id in session_ids:
            await self.terminate_session(session_id)
        logger.info("Terminated all sessions (%d total)", len(session_ids))

    async def _process_session_loop(
        self,
        initial_session_id: str,
        input_queue: asyncio.Queue[str],
        client: ClaudeSDKClient,
    ) -> None:
        """
        Background processing loop for a session.

        Processes messages from input queue, streams responses,
        and handles buffering/early termination.

        Args:
            initial_session_id: Initial session ID ("new" or Claude UUID)
            input_queue: Queue for user messages
            client: ClaudeSDKClient instance
        """
        session_id = initial_session_id
        state: AgentSessionState | None = None

        try:
            # Initialize SDK client
            await client.__aenter__()

            logger.info("Agent processing loop started (session=%s)", session_id)

            while True:
                # Wait for user message
                user_message = await input_queue.get()

                # Update state reference
                if state is None:
                    state = self.sessions.get(session_id)

                if state:
                    state.is_processing = True

                logger.info("Processing message for session %s", session_id)

                # Process message and stream events
                async for event in self.agent_service.process_message_stream(client, user_message):
                    # Capture session ID from init event
                    if event.get("type") == "session_id":
                        new_session_id = event["session_id"]
                        if new_session_id != session_id:
                            logger.info("Session ID captured: %s", new_session_id)
                            session_id = new_session_id

                            # Move session state to new ID
                            async with self._lock:
                                if initial_session_id in self.sessions:
                                    state = self.sessions.pop(initial_session_id)
                                    state.session_id = session_id
                                    self.sessions[session_id] = state

                    # Update activity
                    if state:
                        state.last_activity = datetime.now(UTC)

                        # Send to WebSocket or buffer
                        if state.connected_ws_id:
                            # Import here to avoid circular dependency
                            from app.api.chat import connection_manager

                            success = await connection_manager.send_message(
                                state.connected_ws_id, event
                            )
                            if not success:
                                logger.warning("Failed to send to WS, buffering")
                                state.message_buffer.append(event)
                        else:
                            # Buffer for later
                            state.message_buffer.append(event)

                    # Check for completion and early termination
                    if event.get("type") == "complete" and state and state.connected_ws_id is None:
                        logger.info(
                            "Response complete with no client, waiting %ds before termination",
                            self.GRACE_PERIOD_SECONDS,
                        )
                        await asyncio.sleep(self.GRACE_PERIOD_SECONDS)

                        # Double-check still disconnected
                        if state.connected_ws_id is None:
                            logger.info("Terminating idle completed session %s", session_id)
                            await self.terminate_session(session_id)
                            return

                if state:
                    state.is_processing = False

                input_queue.task_done()

        except asyncio.CancelledError:
            logger.info("Processing loop cancelled for session %s", session_id)
        except Exception as e:
            logger.exception("Error in processing loop for session %s", session_id)
            # Send error to client if connected
            if state and state.connected_ws_id:
                from app.api.chat import connection_manager

                await connection_manager.send_message(
                    state.connected_ws_id,
                    {
                        "type": "error",
                        "error": str(e),
                    },
                )

    async def _cleanup_once(self) -> None:
        """Run a single cleanup pass for inactive sessions."""
        now = datetime.now(UTC)
        to_terminate = []

        async with self._lock:
            for session_id, state in self.sessions.items():
                # Check for timeout
                inactive_seconds = (now - state.last_activity).total_seconds()
                if inactive_seconds > self.TIMEOUT_SECONDS:
                    logger.info(
                        "Session %s timed out (inactive for %ds)",
                        session_id,
                        inactive_seconds,
                    )
                    to_terminate.append(session_id)

        # Terminate outside lock to avoid deadlock
        for session_id in to_terminate:
            await self.terminate_session(session_id)

    @functools.wraps(_cleanup_once)
    async def _cleanup_loop(self) -> None:
        """Background task to cleanup inactive sessions."""
        try:
            while True:
                await asyncio.sleep(60)  # Check every minute
                await self._cleanup_once()

        except asyncio.CancelledError:
            logger.info("Cleanup loop cancelled")
