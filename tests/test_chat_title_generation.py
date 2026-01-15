"""Unit tests for chat title generation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from claude_agent_sdk import AssistantMessage, TextBlock

from app.services.agent import AgentService


@pytest.mark.asyncio
async def test_generate_chat_title_sanitizes_output(tmp_path: Path) -> None:
    agent = AgentService(vault_path=str(tmp_path), api_key="test-key")

    async def fake_query(*_args, **_kwargs):
        yield AssistantMessage(
            content=[TextBlock('  "Project summary!"\nExtra line')],
            model="test-model",
        )

    with patch("app.services.agent.query", side_effect=fake_query):
        title = await agent.generate_chat_title("user prompt", session_id="session-1")

    assert title == "Project summary"


@pytest.mark.asyncio
async def test_generate_chat_title_truncates_long_output(tmp_path: Path) -> None:
    agent = AgentService(vault_path=str(tmp_path), api_key="test-key")
    long_title = "A" * 120

    async def fake_query(*_args, **_kwargs):
        yield AssistantMessage(
            content=[TextBlock(long_title)],
            model="test-model",
        )

    with patch("app.services.agent.query", side_effect=fake_query):
        title = await agent.generate_chat_title("user prompt", session_id="session-1")

    assert title is not None
    assert len(title) == 80


@pytest.mark.asyncio
async def test_generate_chat_title_returns_none_on_failure(tmp_path: Path) -> None:
    agent = AgentService(vault_path=str(tmp_path), api_key="test-key")

    async def failing_query(*_args, **_kwargs):
        raise RuntimeError("boom")
        if False:  # pragma: no cover - required for async generator
            yield None

    with patch("app.services.agent.query", side_effect=failing_query):
        title = await agent.generate_chat_title("user prompt", session_id="session-1")

    assert title is None
