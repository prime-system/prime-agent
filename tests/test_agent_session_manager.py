"""Unit tests for AgentSessionManager."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from app.services.agent_session_manager import AgentSessionManager


@pytest.fixture
def mock_agent_service():
    """Create mock AgentChatService."""
    service = Mock()
    service.create_client_instance = Mock()
    service.process_message_stream = AsyncMock()
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
async def session_manager(mock_agent_service):
    """Create AgentSessionManager instance."""
    manager = AgentSessionManager(agent_service=mock_agent_service)
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
    """Test termination after completion with no client."""
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

    # Session should be terminated
    assert "test-session" not in session_manager.sessions


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
