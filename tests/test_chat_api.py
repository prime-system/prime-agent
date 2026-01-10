"""Tests for chat API websocket contract and history validation."""

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import chat
from app.dependencies import get_agent_session_manager, get_chat_session_manager
from app.services.agent_session_manager import AgentSessionManager


def _build_chat_client(agent_session_manager, chat_session_manager) -> TestClient:
    app = FastAPI()
    app.include_router(chat.router)
    app.dependency_overrides[get_agent_session_manager] = lambda: agent_session_manager
    app.dependency_overrides[get_chat_session_manager] = lambda: chat_session_manager

    @app.post("/__test__/cleanup")
    async def _cleanup() -> dict[str, bool]:
        await agent_session_manager.terminate_all_sessions()
        return {"ok": True}

    return TestClient(app)


def test_session_messages_invalid_id_returns_400():
    mock_chat_session_manager = MagicMock()
    mock_agent_session_manager = MagicMock()

    with _build_chat_client(mock_agent_session_manager, mock_chat_session_manager) as client:
        response = client.get("/api/v1/chat/sessions/bad$id/messages")

    assert response.status_code == 400
    assert "Invalid session ID" in response.json()["detail"]


def test_websocket_connected_session_id_and_complete():
    mock_agent_service = MagicMock()
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock()

    async def _message_stream(_client, _message):
        yield {"type": "session_id", "session_id": "session-123", "sessionId": "session-123"}
        yield {
            "type": "complete",
            "status": "success",
            "costUsd": 0.02,
            "durationMs": 200,
            "cost_usd": 0.02,
            "duration_ms": 200,
        }

    mock_agent_service.create_client_instance.return_value = mock_client
    mock_agent_service.process_message_stream = _message_stream

    agent_session_manager = AgentSessionManager(agent_service=mock_agent_service)
    mock_chat_session_manager = MagicMock()

    chat.connection_manager.active_connections.clear()
    with _build_chat_client(agent_session_manager, mock_chat_session_manager) as client:
        with client.websocket_connect("/api/v1/chat/ws/new") as ws:
            connected = ws.receive_json()
            assert connected["type"] == "connected"
            assert "connectionId" in connected
            assert "sessionId" not in connected

            ws.send_json({"type": "user_message", "data": {"message": "hello"}})

            session_event = ws.receive_json()
            assert session_event["type"] == "session_id"
            assert session_event["sessionId"] == "session-123"

            complete_event = ws.receive_json()
            assert complete_event["type"] == "complete"
            assert "costUsd" in complete_event
            assert "durationMs" in complete_event

        client.post("/__test__/cleanup")


def test_websocket_error_is_permanent():
    mock_agent_service = MagicMock()
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock()

    async def _message_stream(_client, _message):
        raise RuntimeError("boom")
        if False:  # pragma: no cover - required for async generator
            yield {}

    mock_agent_service.create_client_instance.return_value = mock_client
    mock_agent_service.process_message_stream = _message_stream

    agent_session_manager = AgentSessionManager(agent_service=mock_agent_service)
    mock_chat_session_manager = MagicMock()

    chat.connection_manager.active_connections.clear()
    with _build_chat_client(agent_session_manager, mock_chat_session_manager) as client:
        with client.websocket_connect("/api/v1/chat/ws/new") as ws:
            ws.receive_json()  # connected
            ws.send_json({"type": "user_message", "data": {"message": "hello"}})
            error_event = ws.receive_json()
            assert error_event["type"] == "error"
            assert error_event["isPermanent"] is True

        client.post("/__test__/cleanup")
