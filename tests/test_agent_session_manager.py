"""Unit tests for AgentSessionManager."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny

from app.services.agent_session_manager import AgentSessionManager
from app.services.push_notifications import PushSendSummary


@pytest.fixture
def mock_agent_service():
    """Create mock AgentChatService."""
    service = Mock()
    service.create_client_instance = Mock()
    service.process_message_stream = AsyncMock()
    return service


@pytest.fixture
def mock_title_agent_service():
    """Create mock AgentService for title generation."""
    service = Mock()
    service.generate_chat_title = AsyncMock(return_value="Test title")
    return service


@pytest.fixture
def mock_chat_title_service():
    """Create mock ChatTitleService."""
    service = Mock()
    service.title_exists = AsyncMock(return_value=False)
    service.set_title = AsyncMock()
    return service


@pytest.fixture
def mock_push_notification_service():
    """Create mock PushNotificationService."""
    service = MagicMock()
    service.send_notification = AsyncMock(
        return_value=PushSendSummary(
            sent=1,
            failed=0,
            invalid_tokens_removed=0,
            device_results=[],
        )
    )
    return service


@pytest.fixture
def mock_client():
    """Create mock ClaudeSDKClient."""
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock()
    return client


@pytest.fixture
def mock_connection_manager():
    """Create mock ConnectionManager."""
    manager = AsyncMock()
    manager.send_message = AsyncMock(return_value=True)
    manager.disconnect = AsyncMock()
    return manager


@pytest.fixture
async def session_manager(
    mock_agent_service,
    mock_push_notification_service,
    mock_title_agent_service,
    mock_chat_title_service,
):
    """Create AgentSessionManager instance."""
    manager = AgentSessionManager(
        agent_service=mock_agent_service,
        title_agent_service=mock_title_agent_service,
        chat_title_service=mock_chat_title_service,
        push_notification_service=mock_push_notification_service,
    )
    yield manager
    # Cleanup
    await manager.terminate_all_sessions()


@pytest.mark.asyncio
async def test_create_session(session_manager, mock_agent_service, mock_client):
    """Test creating a new session."""
    mock_agent_service.create_client_instance.return_value = mock_client

    # Create new session
    state = await session_manager.get_or_create_session(None)

    assert state.session_id.startswith("pending_")
    assert state.client == mock_client
    assert isinstance(state.input_queue, asyncio.Queue)
    assert isinstance(state.processing_task, asyncio.Task)
    assert not state.is_processing
    assert state.connected_ws_id is None

    # Cleanup
    state.processing_task.cancel()
    try:
        await state.processing_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_get_running_session_ids(session_manager, mock_agent_service, mock_client):
    """Test reporting running session IDs."""
    mock_agent_service.create_client_instance.return_value = mock_client

    state = await session_manager.get_or_create_session("running-session")
    running_ids = await session_manager.get_running_session_ids()

    assert "running-session" not in running_ids

    state.is_processing = True
    running_ids_active = await session_manager.get_running_session_ids()
    assert "running-session" in running_ids_active

    state.waiting_for_user = True
    running_ids_waiting = await session_manager.get_running_session_ids()
    assert "running-session" not in running_ids_waiting

    await session_manager.terminate_session("running-session")
    running_ids_after = await session_manager.get_running_session_ids()
    assert "running-session" not in running_ids_after


@pytest.mark.asyncio
async def test_pending_session_ids_are_unique(session_manager, mock_agent_service, mock_client):
    """Test that new sessions use unique pending IDs."""
    mock_agent_service.create_client_instance.return_value = mock_client

    state1 = await session_manager.get_or_create_session(None)
    state2 = await session_manager.get_or_create_session(None)

    assert state1.session_id != state2.session_id
    assert state1.session_id.startswith("pending_")
    assert state2.session_id.startswith("pending_")

    # Cleanup
    state1.processing_task.cancel()
    state2.processing_task.cancel()
    try:
        await state1.processing_task
    except asyncio.CancelledError:
        pass
    try:
        await state2.processing_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_session_rekey_on_session_id_event(session_manager, mock_agent_service, mock_client):
    """Test rekeying session when SDK provides a real session ID."""
    mock_agent_service.create_client_instance.return_value = mock_client

    async def _message_stream(_client, _message):
        yield {"type": "session_id", "session_id": "real-session-id"}
        yield {"type": "complete", "status": "success", "cost_usd": 0.01, "duration_ms": 1000}

    mock_agent_service.process_message_stream = _message_stream

    state = await session_manager.get_or_create_session(None)
    pending_id = state.session_id

    queued = await session_manager.send_user_message(pending_id, "test message")
    assert queued

    await asyncio.sleep(0.1)

    assert "real-session-id" in session_manager.sessions
    assert pending_id not in session_manager.sessions
    assert state.session_id == "real-session-id"


@pytest.mark.asyncio
async def test_title_generation_triggered_once_on_new_session(
    session_manager,
    mock_agent_service,
    mock_client,
    mock_title_agent_service,
    mock_chat_title_service,
):
    """Trigger title generation once after rekey for new sessions."""
    mock_agent_service.create_client_instance.return_value = mock_client

    async def _message_stream(_client, _message):
        yield {"type": "session_id", "session_id": "real-session-id"}
        yield {"type": "complete", "status": "success", "cost_usd": 0.01, "duration_ms": 1000}

    mock_agent_service.process_message_stream = _message_stream

    state = await session_manager.get_or_create_session(None)
    queued = await session_manager.send_user_message(state.session_id, "first message")
    assert queued

    await asyncio.sleep(0.1)
    queued = await session_manager.send_user_message(state.session_id, "second message")
    assert queued

    await asyncio.sleep(0.1)

    assert mock_title_agent_service.generate_chat_title.await_count == 1
    mock_chat_title_service.set_title.assert_awaited_once()


@pytest.mark.asyncio
async def test_title_generation_not_triggered_on_resume(
    session_manager,
    mock_agent_service,
    mock_client,
    mock_title_agent_service,
    mock_chat_title_service,
):
    """Skip title generation when resuming an existing session."""
    mock_agent_service.create_client_instance.return_value = mock_client

    async def _message_stream(_client, _message):
        yield {"type": "session_id", "session_id": "existing-session"}
        yield {"type": "complete", "status": "success", "cost_usd": 0.01, "duration_ms": 1000}

    mock_agent_service.process_message_stream = _message_stream

    state = await session_manager.get_or_create_session("existing-session")
    queued = await session_manager.send_user_message(state.session_id, "test message")
    assert queued

    await asyncio.sleep(0.1)

    assert mock_title_agent_service.generate_chat_title.await_count == 0
    assert mock_chat_title_service.set_title.await_count == 0


@pytest.mark.asyncio
async def test_attach_detach_websocket(
    session_manager, mock_agent_service, mock_client, mock_connection_manager
):
    """Test WebSocket attachment lifecycle."""
    mock_agent_service.create_client_instance.return_value = mock_client

    # Create session
    state = await session_manager.get_or_create_session("test-session")
    session_manager.sessions["test-session"] = state

    # Attach WebSocket
    buffered = await session_manager.attach_websocket(
        "test-session", "ws-1", mock_connection_manager
    )

    assert state.connected_ws_id == "ws-1"
    assert buffered == []

    # Detach WebSocket
    await session_manager.detach_websocket("test-session", "ws-1")

    assert state.connected_ws_id is None

    # Cleanup
    state.processing_task.cancel()
    try:
        await state.processing_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_message_buffering(
    session_manager, mock_agent_service, mock_client, mock_connection_manager
):
    """Test message buffering during disconnect."""
    mock_agent_service.create_client_instance.return_value = mock_client

    async def _message_stream():
        yield {"type": "text", "chunk": "Hello"}
        yield {"type": "complete", "status": "success", "cost_usd": 0.01, "duration_ms": 1000}

    mock_agent_service.process_message_stream = lambda *_args, **_kwargs: _message_stream()

    # Create session (not attached)
    state = await session_manager.get_or_create_session("test-session")
    session_manager.sessions["test-session"] = state

    # Send message (will be buffered since no WS attached)
    queued = await session_manager.send_user_message("test-session", "test message")
    assert queued

    # Give processing time to buffer
    await asyncio.sleep(0.1)

    # Attach and check buffer
    buffered = await session_manager.attach_websocket(
        "test-session", "ws-1", mock_connection_manager
    )

    # Buffered messages should be delivered on attach
    assert len(buffered) == 2
    assert buffered[0]["type"] == "text"
    assert buffered[1]["type"] == "complete"
    assert state.last_event_type == "complete"
    assert state.completed_at is not None

    # Cleanup
    state.processing_task.cancel()
    try:
        await state.processing_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_buffer_overflow(session_manager, mock_agent_service, mock_client):
    """Test FIFO eviction at maxlen."""
    mock_agent_service.create_client_instance.return_value = mock_client

    # Create session
    state = await session_manager.get_or_create_session("test-session")
    session_manager.sessions["test-session"] = state

    # Add 150 messages (maxlen=100)
    for i in range(150):
        state.message_buffer.append({"type": "text", "chunk": f"message-{i}"})

    # Should only have last 100
    assert len(state.message_buffer) == 100
    assert state.message_buffer[0]["chunk"] == "message-50"
    assert state.message_buffer[-1]["chunk"] == "message-149"

    # Cleanup
    state.processing_task.cancel()
    try:
        await state.processing_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_terminal_event_retained_when_buffer_full(
    session_manager, mock_agent_service, mock_client, mock_connection_manager
):
    """Ensure terminal event is replayed even if buffer is full."""
    mock_agent_service.create_client_instance.return_value = mock_client

    state = await session_manager.get_or_create_session("test-session")
    session_manager.sessions["test-session"] = state

    for i in range(100):
        state.message_buffer.append({"type": "text", "chunk": f"message-{i}"})

    terminal_event = {"type": "complete", "status": "success"}
    async with state.ws_lock:
        state.last_event_type = "complete"
        state.last_terminal_event = terminal_event

    buffered = await session_manager.attach_websocket(
        "test-session", "ws-1", mock_connection_manager
    )

    assert len(buffered) == 101
    assert buffered[-1] == terminal_event

    # Cleanup
    state.processing_task.cancel()
    try:
        await state.processing_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_session_timeout(session_manager, mock_agent_service, mock_client):
    """Test 30-minute timeout."""
    mock_agent_service.create_client_instance.return_value = mock_client

    # Create session
    state = await session_manager.get_or_create_session("test-session")
    session_manager.sessions["test-session"] = state

    # Simulate old activity
    state.last_activity = datetime.now(UTC) - timedelta(
        seconds=AgentSessionManager.TIMEOUT_SECONDS + 10
    )

    # Run cleanup
    await session_manager._cleanup_once()

    # Session should be terminated
    assert "test-session" not in session_manager.sessions


@pytest.mark.asyncio
async def test_connection_exclusivity(
    session_manager, mock_agent_service, mock_client, mock_connection_manager
):
    """Test single client enforcement."""
    mock_agent_service.create_client_instance.return_value = mock_client

    # Create session
    state = await session_manager.get_or_create_session("test-session")
    session_manager.sessions["test-session"] = state

    # Attach first WebSocket
    await session_manager.attach_websocket("test-session", "ws-1", mock_connection_manager)
    assert state.connected_ws_id == "ws-1"

    # Attach second WebSocket (should kick first)
    await session_manager.attach_websocket("test-session", "ws-2", mock_connection_manager)

    assert state.connected_ws_id == "ws-2"
    mock_connection_manager.send_message.assert_called()
    mock_connection_manager.disconnect.assert_awaited_with("ws-1")

    # Cleanup
    state.processing_task.cancel()
    try:
        await state.processing_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_takeover_rejects_input(
    session_manager, mock_agent_service, mock_client, mock_connection_manager
):
    """Test that a kicked WebSocket cannot enqueue messages."""
    mock_agent_service.create_client_instance.return_value = mock_client

    state = await session_manager.get_or_create_session("test-session")
    session_manager.sessions["test-session"] = state

    await session_manager.attach_websocket("test-session", "ws-1", mock_connection_manager)
    await session_manager.attach_websocket("test-session", "ws-2", mock_connection_manager)

    mock_connection_manager.send_message.reset_mock()
    mock_connection_manager.disconnect.reset_mock()

    accepted = await session_manager.send_user_message(
        "test-session",
        "late message",
        ws_id="ws-1",
        connection_manager=mock_connection_manager,
    )

    assert not accepted
    mock_connection_manager.send_message.assert_awaited_with("ws-1", {"type": "session_taken"})
    mock_connection_manager.disconnect.assert_awaited_with("ws-1")

    # Cleanup
    state.processing_task.cancel()
    try:
        await state.processing_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_replay_ordering(
    session_manager, mock_agent_service, mock_client, mock_connection_manager
):
    """Test that replay preserves ordering with concurrent buffering."""
    mock_agent_service.create_client_instance.return_value = mock_client

    state = await session_manager.get_or_create_session("test-session")
    session_manager.sessions["test-session"] = state

    state.message_buffer.append({"type": "text", "chunk": "msg1"})
    state.message_buffer.append({"type": "text", "chunk": "msg2"})

    buffered = await session_manager.attach_websocket(
        "test-session", "ws-1", mock_connection_manager
    )

    for msg in buffered:
        await mock_connection_manager.send_message("ws-1", msg)

    await session_manager._buffer_event(state, {"type": "text", "chunk": "msg3"})
    await session_manager.finish_replay(state, "ws-1", mock_connection_manager)

    sent_chunks = [
        call.args[1]["chunk"] for call in mock_connection_manager.send_message.call_args_list
    ]
    assert sent_chunks == ["msg1", "msg2", "msg3"]
    assert state.replay_in_progress is False

    # Cleanup
    state.processing_task.cancel()
    try:
        await state.processing_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_reconnect_buffer_replay(
    session_manager, mock_agent_service, mock_client, mock_connection_manager
):
    """Test buffer drain on reconnect."""
    mock_agent_service.create_client_instance.return_value = mock_client

    # Create session
    state = await session_manager.get_or_create_session("test-session")
    session_manager.sessions["test-session"] = state

    # Add buffered messages
    state.message_buffer.append({"type": "text", "chunk": "msg1"})
    state.message_buffer.append({"type": "text", "chunk": "msg2"})

    # Attach WebSocket
    buffered = await session_manager.attach_websocket(
        "test-session", "ws-1", mock_connection_manager
    )

    # Should replay buffer
    assert len(buffered) == 2
    assert buffered[0]["chunk"] == "msg1"
    assert buffered[1]["chunk"] == "msg2"

    # Buffer should be cleared
    assert len(state.message_buffer) == 0

    # Cleanup
    state.processing_task.cancel()
    try:
        await state.processing_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_early_termination(session_manager, mock_agent_service, mock_client):
    """Test completion does not terminate without a client."""
    mock_agent_service.create_client_instance.return_value = mock_client
    session_manager.GRACE_PERIOD_SECONDS = 0

    # Mock process_message_stream to yield complete event
    async def mock_stream(client, message):
        yield {"type": "text", "chunk": "response"}
        yield {"type": "complete", "status": "success", "cost_usd": 0.01, "duration_ms": 1000}

    mock_agent_service.process_message_stream = mock_stream

    # Create session (no WS attached)
    state = await session_manager.get_or_create_session("test-session")
    session_manager.sessions["test-session"] = state

    # Send message
    queued = await session_manager.send_user_message("test-session", "test")
    assert queued

    # Allow processing to complete
    await asyncio.sleep(0.1)

    # Session should remain for reconnect
    assert "test-session" in session_manager.sessions
    assert state.completed_at is not None
    assert state.last_event_type == "complete"


@pytest.mark.asyncio
async def test_completion_notification_sent_when_disconnected(
    session_manager, mock_agent_service, mock_client, mock_push_notification_service
):
    """Send notification after completion with no WebSocket."""
    mock_agent_service.create_client_instance.return_value = mock_client
    session_manager.GRACE_PERIOD_SECONDS = 0

    async def mock_stream(_client, _message):
        yield {"type": "complete", "status": "success", "costUsd": 0.01, "durationMs": 1000}

    mock_agent_service.process_message_stream = mock_stream

    state = await session_manager.get_or_create_session("test-session")
    session_manager.sessions["test-session"] = state

    queued = await session_manager.send_user_message("test-session", "test")
    assert queued

    await asyncio.sleep(0.1)

    mock_push_notification_service.send_notification.assert_awaited_once()
    kwargs = mock_push_notification_service.send_notification.call_args.kwargs
    assert kwargs["title"] == "Chat response ready"
    assert kwargs["body"] == "Your chat response is complete."
    assert kwargs["data"]["type"] == "chat_complete"
    assert kwargs["data"]["session_id"] == "test-session"
    assert kwargs["data"]["status"] == "success"
    assert kwargs["data"]["deeplink_url"] == "prime://chat/session/test-session"
    assert kwargs["data"]["costUsd"] == 0.01
    assert kwargs["data"]["durationMs"] == 1000

    assert "test-session" in session_manager.sessions


@pytest.mark.asyncio
async def test_completion_notification_skipped_when_connected(
    session_manager,
    mock_agent_service,
    mock_client,
    mock_push_notification_service,
    mock_connection_manager,
    monkeypatch,
):
    """Skip notification when a WebSocket is connected."""
    mock_agent_service.create_client_instance.return_value = mock_client
    session_manager.GRACE_PERIOD_SECONDS = 0

    async def mock_stream(_client, _message):
        yield {"type": "complete", "status": "success"}

    mock_agent_service.process_message_stream = mock_stream
    monkeypatch.setattr("app.api.chat.connection_manager", mock_connection_manager)

    state = await session_manager.get_or_create_session("test-session")
    session_manager.sessions["test-session"] = state
    async with state.ws_lock:
        state.connected_ws_id = "ws-1"

    queued = await session_manager.send_user_message("test-session", "test")
    assert queued

    await asyncio.sleep(0.1)

    mock_push_notification_service.send_notification.assert_not_called()
    assert "test-session" in session_manager.sessions


@pytest.mark.asyncio
async def test_completion_notification_skipped_on_reconnect_during_grace(
    session_manager,
    mock_agent_service,
    mock_client,
    mock_push_notification_service,
):
    """Skip notification if WebSocket reconnects during grace period."""
    mock_agent_service.create_client_instance.return_value = mock_client
    session_manager.GRACE_PERIOD_SECONDS = 0.1

    async def mock_stream(_client, _message):
        yield {"type": "complete", "status": "success"}

    mock_agent_service.process_message_stream = mock_stream

    state = await session_manager.get_or_create_session("test-session")
    session_manager.sessions["test-session"] = state

    async def reconnect():
        await asyncio.sleep(0.05)
        async with state.ws_lock:
            state.connected_ws_id = "ws-1"

    asyncio.create_task(reconnect())

    queued = await session_manager.send_user_message("test-session", "test")
    assert queued

    await asyncio.sleep(0.2)

    mock_push_notification_service.send_notification.assert_not_called()
    assert "test-session" in session_manager.sessions


@pytest.mark.asyncio
async def test_completion_notification_failure_does_not_raise(
    session_manager,
    mock_agent_service,
    mock_client,
    mock_push_notification_service,
):
    """Notification failures should not crash the session loop."""
    mock_agent_service.create_client_instance.return_value = mock_client
    session_manager.GRACE_PERIOD_SECONDS = 0

    async def mock_stream(_client, _message):
        yield {"type": "complete", "status": "success"}

    mock_agent_service.process_message_stream = mock_stream
    mock_push_notification_service.send_notification.side_effect = RuntimeError("fail")

    state = await session_manager.get_or_create_session("test-session")
    session_manager.sessions["test-session"] = state

    queued = await session_manager.send_user_message("test-session", "test")
    assert queued

    await asyncio.sleep(0.1)
    assert "test-session" in session_manager.sessions


@pytest.mark.asyncio
async def test_processing_loop_exception_cleanup(
    session_manager, mock_agent_service, mock_client, mock_connection_manager, monkeypatch
):
    """Test cleanup and error notification on processing loop failure."""
    mock_agent_service.create_client_instance.return_value = mock_client

    async def _message_stream(_client, _message):
        raise RuntimeError("boom")
        if False:  # pragma: no cover - required for async generator
            yield {}

    mock_agent_service.process_message_stream = _message_stream
    monkeypatch.setattr("app.api.chat.connection_manager", mock_connection_manager)

    state = await session_manager.get_or_create_session("test-session")
    session_manager.sessions["test-session"] = state

    await session_manager.attach_websocket("test-session", "ws-1", mock_connection_manager)
    accepted = await session_manager.send_user_message(
        "test-session",
        "trigger",
        ws_id="ws-1",
        connection_manager=mock_connection_manager,
    )
    assert accepted

    await asyncio.wait_for(state.processing_task, timeout=1)

    assert "test-session" not in session_manager.sessions
    error_payload = mock_connection_manager.send_message.call_args_list[-1].args[1]
    assert error_payload["type"] == "error"
    assert error_payload["isPermanent"] is True
    mock_connection_manager.disconnect.assert_awaited_with("ws-1")


@pytest.mark.asyncio
async def test_terminate_all_sessions(session_manager, mock_agent_service, mock_client):
    """Test terminating all sessions."""
    mock_agent_service.create_client_instance.return_value = mock_client

    # Create multiple sessions
    state1 = await session_manager.get_or_create_session("session-1")
    session_manager.sessions["session-1"] = state1

    state2 = await session_manager.get_or_create_session("session-2")
    session_manager.sessions["session-2"] = state2

    # Terminate all
    await session_manager.terminate_all_sessions()

    # All should be gone
    assert len(session_manager.sessions) == 0


@pytest.mark.asyncio
async def test_normalize_ask_user_answers(session_manager) -> None:
    """Normalize multi-select and free text responses."""
    normalized = session_manager._normalize_ask_user_answers(
        {
            "How should I format the output?": ["Summary", "Detailed"],
            "Notes": "Free text",
        },
    )

    assert normalized == {
        "How should I format the output?": "Summary, Detailed",
        "Notes": "Free text",
    }


@pytest.mark.asyncio
async def test_ask_user_timeout_returns_deny(
    session_manager, mock_agent_service, mock_client, monkeypatch
) -> None:
    """Timeouts should deny with interrupt."""
    mock_agent_service.create_client_instance.return_value = mock_client
    monkeypatch.setattr(session_manager, "ASK_USER_TIMEOUT_SECONDS", 0.01)

    state = await session_manager.get_or_create_session("test-session")
    session_manager.sessions["test-session"] = state

    result = await session_manager._handle_ask_user_question(
        state,
        {"questions": [{"question": "Pick one"}]},
    )

    assert isinstance(result, PermissionResultDeny)
    assert result.behavior == "deny"
    assert result.interrupt is True


@pytest.mark.asyncio
async def test_ask_user_question_response_allows(
    session_manager, mock_agent_service, mock_client, monkeypatch
) -> None:
    """AskUserQuestion should emit event and accept responses."""

    class FakeConnectionManager:
        def __init__(self) -> None:
            self.sent = asyncio.Queue()

        async def send_message(self, ws_id: str, message: dict[str, object]) -> bool:
            await self.sent.put((ws_id, message))
            return True

        async def disconnect(self, ws_id: str) -> None:
            return None

    mock_agent_service.create_client_instance.return_value = mock_client
    fake_connection_manager = FakeConnectionManager()
    monkeypatch.setattr("app.api.chat.connection_manager", fake_connection_manager)

    state = await session_manager.get_or_create_session("test-session")
    session_manager.sessions["test-session"] = state

    async with state.ws_lock:
        state.connected_ws_id = "ws-1"

    ask_task = asyncio.create_task(
        session_manager._handle_ask_user_question(
            state,
            {"questions": [{"question": "How should I format the output?"}]},
        )
    )

    ws_id, message = await asyncio.wait_for(fake_connection_manager.sent.get(), timeout=1)
    assert ws_id == "ws-1"
    assert message["type"] == "ask_user_question"

    outcome, error = await session_manager.submit_ask_user_response(
        "test-session",
        message["question_id"],
        {"How should I format the output?": "Summary"},
        ws_id="ws-1",
        connection_manager=fake_connection_manager,
    )
    assert outcome == "accepted"
    assert error is None

    result = await asyncio.wait_for(ask_task, timeout=1)
    assert isinstance(result, PermissionResultAllow)
    assert result.behavior == "allow"
    assert result.updated_input is not None
    assert result.updated_input["answers"]["How should I format the output?"] == "Summary"


@pytest.mark.asyncio
async def test_ask_user_question_buffered_until_reconnect(
    session_manager, mock_agent_service, mock_client, mock_connection_manager
) -> None:
    """AskUserQuestion should buffer while disconnected and replay on attach."""
    mock_agent_service.create_client_instance.return_value = mock_client

    state = await session_manager.get_or_create_session("test-session")
    session_manager.sessions["test-session"] = state

    ask_task = asyncio.create_task(
        session_manager._handle_ask_user_question(
            state,
            {"questions": [{"question": "Pick one"}]},
        )
    )
    for _ in range(50):
        async with state.ws_lock:
            if state.pending_question_id:
                break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("Pending question was not created in time")

    buffered = await session_manager.attach_websocket(
        "test-session",
        "ws-1",
        mock_connection_manager,
    )
    ask_event = next(event for event in buffered if event["type"] == "ask_user_question")

    outcome, _ = await session_manager.submit_ask_user_response(
        "test-session",
        ask_event["question_id"],
        {"Pick one": ["A", "B"]},
        ws_id="ws-1",
        connection_manager=mock_connection_manager,
    )
    assert outcome == "accepted"

    result = await asyncio.wait_for(ask_task, timeout=1)
    assert result.behavior == "allow"
    assert result.updated_input is not None
    assert result.updated_input["answers"]["Pick one"] == "A, B"
