"""
Agent service for multi-turn chat with Agent SDK integration.

This module provides streaming responses for chat sessions using the
Claude Agent SDK. Sessions are persisted natively by the Agent SDK.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)

from app.models.chat import SSEEventType
from app.services.git import GitService

logger = logging.getLogger(__name__)


class AgentChatService:
    """
    Manages Claude Agent SDK client for multi-turn chat conversations.

    Uses ClaudeSDKClient to maintain persistent session context across
    multiple user messages, enabling true multi-turn conversations.

    Sessions are persisted natively by the Agent SDK in Claude Code's
    session logs. No separate session storage is needed.
    """

    def __init__(
        self,
        vault_path: str,
        api_key: str,
        model: str,
        base_url: str | None = None,
        git_service: GitService | None = None,
    ):
        """
        Initialize agent chat service.

        Args:
            vault_path: Absolute path to vault directory
            api_key: Anthropic API key
            model: Agent model name (required)
            base_url: Optional custom API endpoint
            git_service: Optional GitService for automatic commit/push
        """
        self.vault_path = Path(vault_path)
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.git_service = git_service

    def _create_agent_options(
        self,
        config: dict[str, Any] | None = None,
        resume: str | None = None,
    ) -> ClaudeAgentOptions:
        """
        Create ClaudeAgentOptions from configuration.

        Args:
            config: Optional configuration overrides
            resume: Optional Claude session ID to resume

        Returns:
            ClaudeAgentOptions configured for Prime
        """
        config = config or {}

        # Build environment dict for API authentication
        env_dict = {"ANTHROPIC_API_KEY": self.api_key}
        if self.base_url:
            env_dict["ANTHROPIC_BASE_URL"] = self.base_url

        options = ClaudeAgentOptions(
            allowed_tools=config.get(
                "allowed_tools",
                ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "Skill", "WebSearch", "WebFetch"],
            ),
            permission_mode=config.get("permission_mode", "acceptEdits"),
            system_prompt={
                "type": "preset",
                "preset": "claude_code",
            },
            setting_sources=["project"],
            cwd=str(self.vault_path),
            env=env_dict,
        )

        if resume:
            options.resume = resume

        return options

    def _process_message(
        self,
        message: Any,
    ) -> dict[str, Any] | None:
        """
        Convert SDK message to SSE event.

        Handles AssistantMessage with content blocks (TextBlock, ToolUseBlock, ThinkingBlock).
        Skips SystemMessage and other non-content messages.

        Args:
            message: Message from ClaudeSDKClient

        Returns:
            Event dict or None if not a streamable message
        """
        # Skip system messages - they're handled separately
        if isinstance(message, SystemMessage):
            return None

        if isinstance(message, AssistantMessage):
            # Process content blocks
            for block in message.content:
                if isinstance(block, TextBlock):
                    return {
                        "type": SSEEventType.TEXT.value,
                        "chunk": block.text,
                    }
                if isinstance(block, ToolUseBlock):
                    return {
                        "type": SSEEventType.TOOL_USE.value,
                        "name": block.name,
                        "input": block.input,
                    }
                if isinstance(block, ThinkingBlock):
                    return {
                        "type": SSEEventType.THINKING.value,
                        "content": block.thinking,
                    }

        return None

    def create_client_instance(self, session_id: str | None = None) -> ClaudeSDKClient:
        """
        Create long-lived ClaudeSDKClient for session manager.

        Args:
            session_id: Optional Claude session ID to resume

        Returns:
            ClaudeSDKClient instance (not yet initialized)
        """
        options = self._create_agent_options(resume=session_id)
        return ClaudeSDKClient(options=options)

    async def process_message_stream(
        self,
        client: ClaudeSDKClient,
        user_message: str,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Process single message and yield events.

        Args:
            client: ClaudeSDKClient instance (already initialized)
            user_message: User message to process

        Yields:
            Event dictionaries (session_id, text, tool_use, thinking, complete, error)
        """
        try:
            # Query agent
            await client.query(user_message)

            # Stream response
            async for message in client.receive_response():
                # Capture SDK session ID from init message
                if isinstance(message, SystemMessage) and message.subtype == "init":
                    sdk_session_id = message.data.get("session_id")
                    if sdk_session_id:
                        logger.info("Captured Claude session ID: %s", sdk_session_id)
                        yield {
                            "type": "session_id",
                            "session_id": sdk_session_id,
                        }

                # Convert to event and yield
                event = self._process_message(message)
                if event:
                    yield event

                # Handle result message
                if isinstance(message, ResultMessage):
                    logger.info(
                        "Agent response complete. Cost: $%.4f, Duration: %dms",
                        message.total_cost_usd,
                        message.duration_ms,
                    )

                    yield {
                        "type": "complete",
                        "status": "success",
                        "cost_usd": message.total_cost_usd,
                        "duration_ms": message.duration_ms,
                    }

        except Exception as e:
            logger.exception("Error in process_message_stream")
            yield {
                "type": "error",
                "error": str(e),
            }

    async def stream_response_ws(
        self,
        message_generator: AsyncGenerator[str, None],
        session_id: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Stream agent responses for WebSocket connection.

        Consumes messages from async generator (fed by queue),
        processes them via Agent SDK, and yields events.

        Args:
            message_generator: Async generator yielding user messages
            session_id: Optional Claude session ID to resume
            config: Optional configuration overrides

        Yields:
            Event dictionaries with type, content, and session_id
        """
        try:
            logger.debug("stream_response_ws starting (session_id=%s)", session_id)

            options = self._create_agent_options(config=config, resume=session_id)

            if session_id:
                logger.info("Resuming Claude session %s", session_id)
            else:
                logger.debug("Creating new Claude session")

            async with ClaudeSDKClient(options=options) as client:
                logger.info("Created agent client (resume=%s)", session_id)

                current_session_id = session_id  # Track session ID

                # Process messages from generator
                async for user_message in message_generator:
                    logger.info(
                        "Processing message (session=%s): %s...",
                        current_session_id,
                        user_message[:50],
                    )

                    # Query agent
                    await client.query(user_message)

                    # Stream response
                    async for message in client.receive_response():
                        # Capture SDK session ID from init message
                        if isinstance(message, SystemMessage) and message.subtype == "init":
                            sdk_session_id = message.data.get("session_id")
                            if sdk_session_id:
                                current_session_id = sdk_session_id
                                logger.info("Captured Claude session ID: %s", sdk_session_id)
                                # Yield session_id event
                                yield {
                                    "type": "session_id",
                                    "session_id": sdk_session_id,
                                }

                        # Convert to event and yield
                        event = self._process_message(message)
                        if event:
                            yield event

                        # Handle result message
                        if isinstance(message, ResultMessage):
                            logger.info(
                                "Agent response complete (session=%s). Cost: $%.4f, Duration: %dms",
                                current_session_id,
                                message.total_cost_usd,
                                message.duration_ms,
                            )

                            # Auto-commit disabled for chat - rely on periodic pull only
                            # if self.git_service and not message.is_error:
                            #     logger.info("Auto-committing changes...")  # noqa: ERA001
                            #     self.git_service.auto_commit_and_push()  # noqa: ERA001

                            yield {
                                "type": SSEEventType.COMPLETE.value,
                                "status": "success",
                                "cost_usd": message.total_cost_usd,
                                "duration_ms": message.duration_ms,
                                "session_id": current_session_id,
                            }

        except asyncio.CancelledError:
            logger.info("stream_response_ws cancelled")
            raise
        except Exception as e:
            logger.exception("Error in stream_response_ws")
            yield {
                "type": SSEEventType.ERROR.value,
                "error": str(e),
            }
