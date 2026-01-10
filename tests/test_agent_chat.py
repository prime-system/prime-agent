"""Unit tests for AgentChatService message processing."""

from claude_agent_sdk import AssistantMessage, TextBlock, ThinkingBlock, ToolUseBlock

from app.services.agent_chat import AgentChatService


def test_process_message_multi_block():
    """Ensure all assistant blocks are emitted in order."""
    service = AgentChatService(
        vault_path="/tmp",
        api_key="test-key",
        model="test-model",
    )

    message = AssistantMessage(
        content=[
            TextBlock("hello"),
            ToolUseBlock(id="tool-1", name="Read", input={"path": "notes.md"}),
            ThinkingBlock(thinking="hmm", signature="sig"),
            TextBlock("second"),
        ],
        model="test-model",
    )

    events = service._process_message(message)

    assert [event["type"] for event in events] == ["text", "tool_use", "thinking", "text"]
    assert events[0]["chunk"] == "hello"
    assert events[1]["name"] == "Read"
    assert events[2]["content"] == "hmm"
    assert events[3]["chunk"] == "second"
