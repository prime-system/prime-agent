"""
Agent Session Manager for persistent, WebSocket-independent sessions.

This module decouples Agent session lifecycle from WebSocket connections,
enabling sessions to persist across reconnections.
"""

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict
from uuid import uuid4

from claude_agent_sdk import ClaudeSDKClient
from claude_agent_sdk.types import (
    CanUseTool,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from app.services.agent_chat import AgentChatService
from app.services.push_notifications import PushNotificationService

logger = logging.getLogger(__name__)


class AskUserResponsePayload(TypedDict):
    """Response payload for AskUserQuestion answers."""

    answers: dict[str, str | list[str]]
    cancelled: bool


AskUserResponseOutcome = Literal["accepted", "invalid", "ignored", "session_taken"]


@dataclass
class AgentSessionState:
    """State for a long-lived agent session."""

    session_id: str
    client: ClaudeSDKClient
    processing_task: asyncio.Task[None]
    input_queue: asyncio.Queue[str]
    message_buffer: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=100))
    last_activity: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    last_event_type: str | None = None
    last_terminal_event: dict[str, Any] | None = None
    connected_ws_id: str | None = None
    is_processing: bool = False
    replay_in_progress: bool = False
    ws_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending_question_id: str | None = None
    pending_question: dict[str, Any] | None = None
    pending_answer_future: asyncio.Future[AskUserResponsePayload] | None = None
    pending_question_started_at: float | None = None
    waiting_for_user: bool = False


class AgentSessionManager:
    """
    Manages long-lived agent sessions independent of WebSocket connections.

    Features:
    - Sessions persist across WebSocket disconnects
    - Message buffering during disconnection
    - 30-minute timeout for inactive sessions
    - Exclusive connections (one client at a time)
    - Push notification when response completes without a connected client
    - Sessions remain available for reconnect until timeout
    """

    TIMEOUT_SECONDS = 1800  # 30 minutes
    GRACE_PERIOD_SECONDS = 5  # After completion, wait before notification
    ASK_USER_TIMEOUT_SECONDS = 55

    def __init__(
        self,
        agent_service: AgentChatService,
        push_notification_service: PushNotificationService,
    ):
        """
        Initialize agent session manager.

        Args:
            agent_service: AgentChatService for creating SDK clients
            push_notification_service: PushNotificationService for completion notifications
        """
        self.agent_service = agent_service
        self.push_notification_service = push_notification_service
        self.sessions: dict[str, AgentSessionState] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task[None] | None = None

    def _generate_pending_session_id(self) -> str:
        """Generate a unique temporary session ID for new sessions."""
        while True:
            pending_id = f"pending_{uuid4().hex}"
            if pending_id not in self.sessions:
                return pending_id

    def has_session(self, session_id: str) -> bool:
        """Check if an agent session is currently held in memory."""
        if not session_id:
            return False
        return session_id in self.sessions

    async def get_running_session_ids(self) -> set[str]:
        """Return session IDs with active processing tasks."""
        async with self._lock:
            return {
                session_id
                for session_id, state in self.sessions.items()
                if not state.processing_task.done()
            }

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

            # Ensure new sessions have unique temporary IDs
            temp_session_id = session_id or self._generate_pending_session_id()

            state_ref: dict[str, AgentSessionState] = {}
            can_use_tool = self._build_can_use_tool_handler(state_ref)

            # Create long-lived ClaudeSDKClient
            client = self.agent_service.create_client_instance(
                session_id=session_id,
                can_use_tool=can_use_tool,
            )

            # Create state
            input_queue: asyncio.Queue[str] = asyncio.Queue()
            processing_task = asyncio.create_task(
                self._process_session_loop(temp_session_id, input_queue, client)
            )
            temp_state = AgentSessionState(
                session_id=temp_session_id,
                client=client,
                processing_task=processing_task,
                input_queue=input_queue,
            )
            state_ref["state"] = temp_state

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

        previous_ws_id: str | None = None
        async with state.ws_lock:
            if state.connected_ws_id and state.connected_ws_id != ws_id:
                previous_ws_id = state.connected_ws_id

            # Attach new client and start replay mode
            state.connected_ws_id = ws_id
            state.last_activity = datetime.now(UTC)
            state.replay_in_progress = True

            # Drain and return buffered messages
            buffered = list(state.message_buffer)
            state.message_buffer.clear()
            terminal_event = (
                state.last_terminal_event
                if state.last_event_type in {"complete", "error"}
                else None
            )

        if terminal_event and not any(event == terminal_event for event in buffered):
            buffered.append(terminal_event)

        async with state.ws_lock:
            pending_question = state.pending_question if state.waiting_for_user else None

        if pending_question and not any(event == pending_question for event in buffered):
            buffered.append(pending_question)

        # Kick previous client if exists
        if previous_ws_id:
            logger.info(
                "Kicking previous client %s (new client: %s)",
                previous_ws_id,
                ws_id,
            )
            await connection_manager.send_message(
                previous_ws_id,
                {"type": "session_taken"},
            )
            await connection_manager.disconnect(previous_ws_id)

        logger.info(
            "Attached WebSocket %s to session %s (buffered: %d)",
            ws_id,
            session_id,
            len(buffered),
        )
        return buffered

    async def finish_replay(
        self,
        state: AgentSessionState,
        ws_id: str,
        connection_manager: Any,
    ) -> None:
        """
        Finish replay after sending buffered messages.

        Ensures events that arrive during replay are sent in order
        before resuming live streaming.
        """
        while True:
            async with state.ws_lock:
                if state.connected_ws_id != ws_id:
                    state.replay_in_progress = False
                    return

                if not state.message_buffer:
                    state.replay_in_progress = False
                    return

                pending = list(state.message_buffer)
                state.message_buffer.clear()

            for event in pending:
                await connection_manager.send_message(ws_id, event)

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

        async with state.ws_lock:
            # Only detach if this is the currently attached client
            if state.connected_ws_id == ws_id:
                state.connected_ws_id = None
                state.replay_in_progress = False
                logger.info("Detached WebSocket %s from session %s", ws_id, session_id)

    async def send_user_message(
        self,
        session_id: str,
        message: str,
        ws_id: str | None = None,
        connection_manager: Any | None = None,
    ) -> bool:
        """
        Queue user message for processing.

        Args:
            session_id: Agent session ID
            message: User message content
        """
        state = self.sessions.get(session_id)
        if not state:
            logger.error("Cannot send message to non-existent session %s", session_id)
            return False

        if ws_id is not None:
            async with state.ws_lock:
                active_ws_id = state.connected_ws_id

            if active_ws_id != ws_id:
                logger.warning(
                    "Rejected message from non-active WebSocket %s (active=%s)",
                    ws_id,
                    active_ws_id,
                )
                if connection_manager:
                    await connection_manager.send_message(
                        ws_id,
                        {"type": "session_taken"},
                    )
                    await connection_manager.disconnect(ws_id)
                return False

        await state.input_queue.put(message)
        state.last_activity = datetime.now(UTC)
        logger.debug("Queued message for session %s", session_id)
        return True

    async def submit_ask_user_response(
        self,
        session_id: str,
        question_id: str,
        answers: dict[str, str | list[str]],
        *,
        cancelled: bool = False,
        ws_id: str | None = None,
        connection_manager: Any | None = None,
    ) -> tuple[AskUserResponseOutcome, str | None]:
        """
        Submit a response for a pending AskUserQuestion.

        Returns an outcome status and optional error message.
        """
        state = self.sessions.get(session_id)
        if not state:
            logger.warning("AskUser response received for unknown session %s", session_id)
            return "ignored", None

        if ws_id is not None:
            async with state.ws_lock:
                active_ws_id = state.connected_ws_id

            if active_ws_id != ws_id:
                logger.warning(
                    "Rejected AskUser response from non-active WebSocket %s (active=%s)",
                    ws_id,
                    active_ws_id,
                )
                if connection_manager:
                    await connection_manager.send_message(
                        ws_id,
                        {"type": "session_taken"},
                    )
                    await connection_manager.disconnect(ws_id)
                return "session_taken", None

        async with state.ws_lock:
            waiting_for_user = state.waiting_for_user
            pending_question_id = state.pending_question_id
            pending_future = state.pending_answer_future

        if not waiting_for_user or not pending_question_id or not pending_future:
            return "ignored", None

        if question_id != pending_question_id:
            return "invalid", "Question ID does not match pending question"

        if pending_future.done():
            return "ignored", None

        if not cancelled:
            error = self._validate_ask_user_answers(answers)
            if error:
                return "invalid", error

        pending_future.set_result(
            {
                "answers": answers,
                "cancelled": cancelled,
            }
        )
        return "accepted", None

    async def terminate_session(self, session_id: str) -> None:
        """
        Terminate session and cleanup resources.

        Args:
            session_id: Agent session ID to terminate
        """
        async with self._lock:
            state = self.sessions.get(session_id)
        if not state:
            return

        if not state.processing_task.done():
            state.processing_task.cancel()
            try:
                await state.processing_task
            except asyncio.CancelledError:
                pass

        async with self._lock:
            still_present = self.sessions.get(state.session_id) is state

        if still_present:
            await self._cleanup_state(state)

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
        and handles buffering/notifications.

        Args:
            initial_session_id: Initial session ID ("new" or Claude UUID)
            input_queue: Queue for user messages
            client: ClaudeSDKClient instance
        """
        session_id = initial_session_id
        state: AgentSessionState | None = None
        fatal_error: dict[str, Any] | None = None
        cancel_exc: asyncio.CancelledError | None = None

        try:
            # Initialize SDK client
            await client.__aenter__()

            logger.info("Agent processing loop started (session=%s)", session_id)

            while True:
                # Wait for user message
                user_message = await input_queue.get()
                terminate_after_message = False

                try:
                    # Update state reference
                    if state is None:
                        state = self.sessions.get(session_id)

                    if state:
                        state.is_processing = True

                    logger.info("Processing message for session %s", session_id)

                    # Process message and stream events
                    async for event in self.agent_service.process_message_stream(
                        client, user_message
                    ):
                        # Capture session ID from init event
                        if event.get("type") == "session_id":
                            new_session_id = event.get("session_id") or event.get("sessionId")
                            if new_session_id and new_session_id != session_id and state:
                                logger.info("Session ID captured: %s", new_session_id)
                                session_id = await self._rekey_session(state, new_session_id)

                        # Update activity
                        if state:
                            state.last_activity = datetime.now(UTC)

                            # Send to WebSocket or buffer
                            await self._dispatch_event(state, event)

                            # Check for completion and offline notification
                            if event.get(
                                "type"
                            ) == "complete" and await self._handle_completion_event(state, event):
                                terminate_after_message = True

                finally:
                    if state:
                        state.is_processing = False
                    input_queue.task_done()

                if terminate_after_message:
                    logger.info("Terminating idle completed session %s", session_id)
                    break

        except asyncio.CancelledError as exc:
            logger.info("Processing loop cancelled for session %s", session_id)
            cancel_exc = exc
        except Exception as e:
            logger.exception("Error in processing loop for session %s", session_id)
            fatal_error = {
                "type": "error",
                "error": str(e),
                "isPermanent": True,
            }
        finally:
            if state is None:
                state = self.sessions.get(session_id)

            if cancel_exc:
                await asyncio.shield(self._cleanup_state(state, error_event=fatal_error))
            else:
                await self._cleanup_state(state, error_event=fatal_error)

            if cancel_exc:
                raise cancel_exc

    async def _dispatch_event(self, state: AgentSessionState, event: dict[str, Any]) -> None:
        """Send event to active WebSocket or buffer it if unavailable."""
        event_type = event.get("type")
        now = datetime.now(UTC)

        async with state.ws_lock:
            state.last_activity = now
            state.last_event_type = event_type
            if event_type in {"complete", "error"}:
                state.completed_at = now
                state.last_terminal_event = event
            connected_ws_id = state.connected_ws_id
            replaying = state.replay_in_progress

        if connected_ws_id and not replaying:
            # Import here to avoid circular dependency
            from app.api.chat import connection_manager

            success = await connection_manager.send_message(connected_ws_id, event)
            if not success:
                logger.warning("Failed to send to WS, buffering")
                await self._buffer_event(state, event)
            return

        await self._buffer_event(state, event)

    async def _buffer_event(self, state: AgentSessionState, event: dict[str, Any]) -> None:
        """Buffer event for later replay."""
        async with state.ws_lock:
            state.message_buffer.append(event)

    async def _handle_completion_event(
        self,
        state: AgentSessionState,
        event: dict[str, Any],
    ) -> bool:
        """Handle completion events and decide whether to notify."""
        async with state.ws_lock:
            connected = state.connected_ws_id is not None

        if connected:
            return False

        logger.info(
            "Response complete with no client, waiting %ds before notification",
            self.GRACE_PERIOD_SECONDS,
        )
        await asyncio.sleep(self.GRACE_PERIOD_SECONDS)

        async with state.ws_lock:
            still_disconnected = state.connected_ws_id is None

        if not still_disconnected:
            return False

        await self._send_completion_notification(state, event)
        return False

    async def _send_completion_notification(
        self,
        state: AgentSessionState,
        event: dict[str, Any],
    ) -> None:
        """Send push notification for completed responses when disconnected."""
        status_value = event.get("status") or "success"
        session_id = event.get("session_id") or event.get("sessionId") or state.session_id
        data: dict[str, Any] = {
            "type": "chat_complete",
            "session_id": session_id,
            "status": status_value,
            "deeplink_url": f"prime://chat/session/{session_id}",
        }

        for key in ("costUsd", "durationMs"):
            if key in event and event[key] is not None:
                data[key] = event[key]

        try:
            summary = await self.push_notification_service.send_notification(
                title="Chat response ready",
                body="Your chat response is complete.",
                data=data,
            )
            logger.info(
                "Chat completion notification sent",
                extra={
                    "session_id": session_id,
                    "sent": summary.sent,
                    "failed": summary.failed,
                    "invalid_tokens_removed": summary.invalid_tokens_removed,
                },
            )
        except Exception as e:
            logger.exception(
                "Failed to send chat completion notification",
                extra={
                    "session_id": session_id,
                    "error": "push_notification_failed",
                    "error_type": type(e).__name__,
                },
            )

    async def _cleanup_state(
        self,
        state: AgentSessionState | None,
        *,
        error_event: dict[str, Any] | None = None,
    ) -> None:
        """Cleanup session resources after processing loop exits."""
        if not state:
            return

        async with self._lock:
            current_state = self.sessions.get(state.session_id)
            if current_state is state:
                self.sessions.pop(state.session_id, None)

        async with state.ws_lock:
            if state.pending_answer_future and not state.pending_answer_future.done():
                state.pending_answer_future.cancel()
            ws_id = state.connected_ws_id
            state.connected_ws_id = None
            state.replay_in_progress = False

        if ws_id:
            from app.api.chat import connection_manager

            if error_event:
                await connection_manager.send_message(ws_id, error_event)
            await connection_manager.disconnect(ws_id)

        # Close SDK client
        try:
            await state.client.__aexit__(None, None, None)
        except Exception as e:
            logger.warning("Error closing SDK client for %s: %s", state.session_id, e)

        logger.info("Terminated session %s", state.session_id)

    async def _rekey_session(self, state: AgentSessionState, new_session_id: str) -> str:
        """Move session state to new session ID."""
        old_session_id = state.session_id
        if new_session_id == old_session_id:
            return old_session_id

        collision_state: AgentSessionState | None = None
        async with self._lock:
            current_state = self.sessions.get(old_session_id)
            if current_state is state:
                self.sessions.pop(old_session_id, None)

            existing_state = self.sessions.get(new_session_id)
            if existing_state and existing_state is not state:
                collision_state = self.sessions.pop(new_session_id, None)

            state.session_id = new_session_id
            self.sessions[new_session_id] = state

        if collision_state:
            logger.warning(
                "Session ID collision detected for %s; terminating prior session",
                new_session_id,
            )
            await self._terminate_state(collision_state)

        return new_session_id

    def _build_can_use_tool_handler(self, state_ref: dict[str, AgentSessionState]) -> CanUseTool:
        """Build can_use_tool handler with access to mutable state reference."""

        async def _can_use_tool(
            tool_name: str,
            tool_input: dict[str, Any],
            context: ToolPermissionContext,
        ) -> PermissionResultAllow | PermissionResultDeny:
            state = state_ref.get("state")
            if not state:
                logger.warning("can_use_tool invoked without session state")
                return PermissionResultDeny(message="Session not ready", interrupt=True)

            if tool_name != "AskUserQuestion":
                return PermissionResultAllow(updated_permissions=context.suggestions)

            return await self._handle_ask_user_question(state, tool_input)

        return _can_use_tool

    async def _handle_ask_user_question(
        self,
        state: AgentSessionState,
        tool_input: dict[str, Any],
    ) -> PermissionResultAllow | PermissionResultDeny:
        """Handle AskUserQuestion tool requests by bridging to WebSocket."""
        questions_value = tool_input.get("questions")
        questions: list[dict[str, Any]]
        if isinstance(questions_value, list):
            questions = [item for item in questions_value if isinstance(item, dict)]
        else:
            questions = []

        question_id = f"q_{uuid4().hex}"
        timeout_seconds = self.ASK_USER_TIMEOUT_SECONDS
        event = {
            "type": "ask_user_question",
            "question_id": question_id,
            "questionId": question_id,
            "questions": questions,
            "timeout_seconds": timeout_seconds,
        }

        loop = asyncio.get_running_loop()
        answer_future: asyncio.Future[AskUserResponsePayload] = loop.create_future()

        async with state.ws_lock:
            if state.pending_answer_future and not state.pending_answer_future.done():
                return PermissionResultDeny(
                    message="Another user question is already pending",
                    interrupt=True,
                )
            state.pending_answer_future = answer_future
            state.pending_question_id = question_id
            state.pending_question = event
            state.pending_question_started_at = time.monotonic()
            state.waiting_for_user = True

        await self._dispatch_event(state, event)

        logger.info(
            "ask_user_question_sent",
            extra={
                "session_id": state.session_id,
                "question_id": question_id,
                "timeout_seconds": timeout_seconds,
            },
        )

        try:
            response = await asyncio.wait_for(answer_future, timeout=timeout_seconds)
        except TimeoutError:
            await self._handle_ask_user_timeout(state, question_id)
            await self._clear_pending_question(state, question_id)
            return PermissionResultDeny(message="User response timeout", interrupt=True)

        duration_seconds = self._get_pending_duration(state)
        await self._clear_pending_question(state, question_id)
        logger.info(
            "ask_user_answer_received",
            extra={
                "session_id": state.session_id,
                "question_id": question_id,
                "duration_seconds": duration_seconds,
            },
        )

        if response["cancelled"]:
            return PermissionResultDeny(message="User cancelled question", interrupt=True)

        normalized_answers = self._normalize_ask_user_answers(response["answers"])
        updated_input = {**tool_input, "questions": questions, "answers": normalized_answers}
        return PermissionResultAllow(updated_input=updated_input)

    def _validate_ask_user_answers(self, answers: dict[str, str | list[str]]) -> str | None:
        """Validate ask_user_response answers payload."""
        for key, value in answers.items():
            if not isinstance(key, str):
                return "Answer keys must be strings"
            if isinstance(value, list):
                if not all(isinstance(item, str) for item in value):
                    return "Answer list values must be strings"
            elif not isinstance(value, str):
                return "Answer values must be strings"
        return None

    def _normalize_ask_user_answers(
        self,
        answers: dict[str, str | list[str]],
    ) -> dict[str, str]:
        """Normalize AskUserQuestion answers into comma-separated strings."""
        normalized: dict[str, str] = {}
        for question_text, value in answers.items():
            if isinstance(value, list):
                normalized[question_text] = ", ".join(value)
            else:
                normalized[question_text] = value
        return normalized

    def _get_pending_duration(self, state: AgentSessionState) -> float | None:
        """Return duration for pending question if start time is recorded."""
        if state.pending_question_started_at is None:
            return None
        return time.monotonic() - state.pending_question_started_at

    async def _handle_ask_user_timeout(self, state: AgentSessionState, question_id: str) -> None:
        """Handle AskUserQuestion timeout by notifying the client."""
        duration_seconds = self._get_pending_duration(state)
        event = {
            "type": "ask_user_timeout",
            "question_id": question_id,
            "questionId": question_id,
            "error": "User response timed out",
        }
        await self._dispatch_event(state, event)
        logger.info(
            "ask_user_timeout",
            extra={
                "session_id": state.session_id,
                "question_id": question_id,
                "duration_seconds": duration_seconds,
            },
        )

    async def _clear_pending_question(self, state: AgentSessionState, question_id: str) -> None:
        """Clear pending question state if it matches the provided question ID."""
        async with state.ws_lock:
            if state.pending_question_id != question_id:
                return
            state.pending_question_id = None
            state.pending_question = None
            state.pending_answer_future = None
            state.pending_question_started_at = None
            state.waiting_for_user = False

    async def _terminate_state(self, state: AgentSessionState) -> None:
        """Terminate a session state instance regardless of registry status."""
        if not state.processing_task.done():
            state.processing_task.cancel()
            try:
                await state.processing_task
            except asyncio.CancelledError:
                pass

        await self._cleanup_state(state)

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

    async def _cleanup_loop(self) -> None:
        """Background task to cleanup inactive sessions."""
        try:
            while True:
                await asyncio.sleep(60)  # Check every minute
                await self._cleanup_once()

        except asyncio.CancelledError:
            logger.info("Cleanup loop cancelled")
