"""Unit tests for AgentSessionManager."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from app.services.agent_session_manager import AgentSessionManager, AgentSessionState


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
    manager.disconnect = Mock()
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

    assert state.session_id == "new"
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
    await session_manager.send_user_message("test-session", "test message")

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
    await session_manager._cleanup_loop.__wrapped__(session_manager)

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
    mock_connection_manager.disconnect.assert_called_with("ws-1")

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

    # Mock process_message_stream to yield complete event
    async def mock_stream(client, message):
        yield {"type": "text", "chunk": "response"}
        yield {"type": "complete", "status": "success", "cost_usd": 0.01, "duration_ms": 1000}

    mock_agent_service.process_message_stream = mock_stream

    # Create session (no WS attached)
    state = await session_manager.get_or_create_session("test-session")
    session_manager.sessions["test-session"] = state

    # Send message
    await session_manager.send_user_message("test-session", "test")

    # Wait for grace period + processing
    await asyncio.sleep(AgentSessionManager.GRACE_PERIOD_SECONDS + 1)

    # Session should be terminated
    assert "test-session" not in session_manager.sessions


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
