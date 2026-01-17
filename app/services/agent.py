"""
Agent service for running commands using Claude Agent SDK.

This module provides the core integration with the Claude Agent SDK,
executing vault-scoped commands that can organize and enrich captures.
"""

import asyncio
import logging
import re
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, TypedDict

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    query,
)

logger = logging.getLogger(__name__)


class ProcessResult(TypedDict):
    """Type definition for agent processing result."""

    success: bool
    cost_usd: float | None
    duration_ms: int | None
    error: str | None


class AgentService:
    """
    Manages Claude Agent SDK invocation for command execution.

    Commands run in the vault directory and can read/update vault content
    according to their instructions.
    """

    def __init__(
        self,
        vault_path: str,
        api_key: str | None = None,
        oauth_token: str | None = None,
        base_url: str | None = None,
        prime_api_url: str | None = None,
        prime_api_token: str | None = None,
        max_budget_usd: float = 2.0,
        timeout_seconds: int = 300,
    ):
        """
        Initialize agent service.

        Args:
            vault_path: Absolute path to vault directory
            api_key: Anthropic API key (optional if oauth_token is set)
            oauth_token: Anthropic OAuth token (optional if api_key is set)
            base_url: Optional custom API endpoint
            prime_api_url: Prime API base URL for notify skill
            prime_api_token: Prime API auth token for notify skill
            max_budget_usd: Maximum cost per command run (safety limit)
            timeout_seconds: Timeout for agent execution in seconds
        """
        if not api_key and not oauth_token:
            msg = "Either api_key or oauth_token must be provided"
            raise ValueError(msg)
        if api_key and oauth_token:
            msg = "Only one of api_key or oauth_token can be provided"
            raise ValueError(msg)

        self.vault_path = Path(vault_path)
        self.api_key = api_key
        self.oauth_token = oauth_token
        self.base_url = base_url
        self.prime_api_url = prime_api_url
        self.prime_api_token = prime_api_token
        self.max_budget_usd = max_budget_usd
        self.timeout_seconds = timeout_seconds

    async def _emit_events_for_message(
        self,
        message: Any,
        event_handler: Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> None:
        """
        Convert SDK message to events and emit via handler.

        Args:
            message: Message from SDK (AssistantMessage or ResultMessage)
            event_handler: Async callback for events (event_type, data)
        """
        if isinstance(message, AssistantMessage):
            # Process content blocks
            for block in message.content:
                if isinstance(block, TextBlock):
                    await event_handler("text", {"chunk": block.text})
                elif isinstance(block, ToolUseBlock):
                    await event_handler("tool_use", {"name": block.name, "input": block.input})
                elif isinstance(block, ThinkingBlock):
                    await event_handler("thinking", {"content": block.thinking})
        elif isinstance(message, SystemMessage) and message.subtype == "init":
            session_id = message.data.get("session_id")
            if session_id:
                await event_handler(
                    "session_id",
                    {
                        "session_id": session_id,
                        "sessionId": session_id,
                    },
                )
        elif isinstance(message, ResultMessage) and message.session_id:
            await event_handler(
                "session_id",
                {
                    "session_id": message.session_id,
                    "sessionId": message.session_id,
                },
            )

    def _build_agent_options(
        self, *, max_budget_usd: float | None = None, model: str | None = None
    ) -> ClaudeAgentOptions:
        """Build ClaudeAgentOptions with optional overrides."""
        # Build environment dict for API authentication
        env_dict: dict[str, str] = {}
        if self.api_key:
            env_dict["ANTHROPIC_API_KEY"] = self.api_key
        elif self.oauth_token:
            env_dict["CLAUDE_CODE_OAUTH_TOKEN"] = self.oauth_token

        if self.base_url:
            env_dict["ANTHROPIC_BASE_URL"] = self.base_url
        if self.prime_api_url:
            env_dict["PRIME_API_URL"] = self.prime_api_url.rstrip("/")
        if self.prime_api_token:
            env_dict["PRIME_API_TOKEN"] = self.prime_api_token

        budget = self.max_budget_usd if max_budget_usd is None else max_budget_usd

        return ClaudeAgentOptions(
            allowed_tools=[
                "Read",
                "Write",
                "Edit",
                "Glob",
                "Grep",
                "Bash",
                "Skill",
                "WebSearch",
                "WebFetch",
            ],
            permission_mode="acceptEdits",  # Auto-approve file operations
            system_prompt={
                "type": "preset",
                "preset": "claude_code",
            },
            setting_sources=["project"],  # Load CLAUDE.md files from project
            cwd=str(self.vault_path),
            env=env_dict,
            max_budget_usd=budget,
            model=model,
        )

    def _build_title_options(
        self, *, max_budget_usd: float, model: str | None = None
    ) -> ClaudeAgentOptions:
        """Build ClaudeAgentOptions for chat title generation."""
        env_dict: dict[str, str] = {}
        if self.api_key:
            env_dict["ANTHROPIC_API_KEY"] = self.api_key
        elif self.oauth_token:
            env_dict["CLAUDE_CODE_OAUTH_TOKEN"] = self.oauth_token

        if self.base_url:
            env_dict["ANTHROPIC_BASE_URL"] = self.base_url

        return ClaudeAgentOptions(
            allowed_tools=[],
            permission_mode="acceptEdits",
            system_prompt="You generate concise chat titles.",
            setting_sources=[],
            cwd=str(self.vault_path),
            env=env_dict,
            max_budget_usd=max_budget_usd,
            model=model,
        )

    @staticmethod
    def _sanitize_chat_title(title: str, max_length: int) -> str:
        cleaned = title.strip()
        if not cleaned:
            return ""

        cleaned = cleaned.splitlines()[0]
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = cleaned.strip("\"'`")
        cleaned = cleaned.strip("\u201c\u201d\u2018\u2019")
        cleaned = cleaned.strip(" .,!?:;")

        if len(cleaned) > max_length:
            cleaned = cleaned[:max_length].rstrip()
            cleaned = cleaned.strip(" .,!?:;")

        return cleaned

    async def generate_chat_title(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
    ) -> str | None:
        """Generate a short chat title from the user's first message."""
        if not prompt or not prompt.strip():
            logger.warning(
                "Chat title generation failed",
                extra={
                    "issue": "title_generation_failed",
                    "session_id": session_id,
                    "error_type": "empty_prompt",
                },
            )
            return None

        title_prompt = (
            "Generate a short chat title (2-6 words) in the same language as the user message. "
            "Return only the title, no quotes, no punctuation. User message: "
            f"{prompt.strip()}"
        )

        options = self._build_title_options(max_budget_usd=0.01)
        title_chunks: list[str] = []

        async def _run_generation() -> None:
            async for message in query(prompt=title_prompt, options=options):
                if isinstance(message, AssistantMessage):
                    text_blocks = [
                        block.text for block in message.content if isinstance(block, TextBlock)
                    ]
                    if text_blocks:
                        title_chunks.extend(text_blocks)

                if isinstance(message, ResultMessage) and message.is_error:
                    msg = "Title generation failed"
                    raise RuntimeError(msg)

        try:
            await asyncio.wait_for(_run_generation(), timeout=20)
        except Exception as e:
            logger.exception(
                "Chat title generation failed",
                extra={
                    "issue": "title_generation_failed",
                    "session_id": session_id,
                    "error_type": type(e).__name__,
                },
            )
            return None

        raw_title = " ".join(title_chunks)
        sanitized = self._sanitize_chat_title(raw_title, max_length=80)
        if not sanitized:
            logger.warning(
                "Chat title generation failed",
                extra={
                    "issue": "title_generation_failed",
                    "session_id": session_id,
                    "error_type": "empty_title",
                },
            )
            return None

        return sanitized

    async def _run_prompt(
        self,
        prompt: str,
        *,
        run_label: str,
        command_name: str | None = None,
        max_budget_usd: float | None = None,
        timeout_seconds: int | None = None,
        model: str | None = None,
        event_handler: Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]] | None = None,
    ) -> ProcessResult:
        """
        Run an agent prompt and collect results.

        Args:
            prompt: User prompt to execute
            run_label: Label for logging
            command_name: Optional command name
            max_budget_usd: Optional budget override
            timeout_seconds: Optional timeout override
            model: Optional model override
            event_handler: Optional async callback for events (event_type, data)

        Returns:
            ProcessResult with success status, cost, duration, and error
        """
        options = self._build_agent_options(max_budget_usd=max_budget_usd, model=model)
        timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds

        logger.info(
            "Starting agent run",
            extra={
                "run_label": run_label,
                "command_name": command_name,
                "prompt_length": len(prompt),
                "timeout_seconds": timeout,
            },
        )

        # Track results
        cost_usd: float | None = None
        duration_ms: int | None = None
        error_msg: str | None = None

        async def _agent_processing() -> None:
            """Inner async function to stream messages from agent."""
            nonlocal cost_usd, duration_ms, error_msg

            async for message in query(
                prompt=prompt,
                options=options,
            ):
                # Convert message to events if handler provided
                if event_handler:
                    await self._emit_events_for_message(message, event_handler)

                if isinstance(message, ResultMessage):
                    cost_usd = message.total_cost_usd
                    duration_ms = message.duration_ms

                    if message.is_error:
                        error_msg = "Agent processing failed"
                        logger.error(
                            "Agent returned error",
                            extra={
                                "run_label": run_label,
                                "command_name": command_name,
                                "agent_message": str(message),
                            },
                        )

        try:
            await asyncio.wait_for(_agent_processing(), timeout=timeout)

            # Emit complete event if handler provided
            if event_handler:
                await event_handler(
                    "complete",
                    {
                        "status": "success" if error_msg is None else "error",
                        "cost_usd": cost_usd,
                        "duration_ms": duration_ms,
                        "costUsd": cost_usd,  # camelCase compat
                        "durationMs": duration_ms,  # camelCase compat
                    },
                )

            return {
                "success": error_msg is None,
                "cost_usd": cost_usd,
                "duration_ms": duration_ms,
                "error": error_msg,
            }

        except TimeoutError:
            error_msg = f"Agent processing timed out after {timeout}s"
            logger.error(
                "Agent processing timed out",
                extra={
                    "run_label": run_label,
                    "command_name": command_name,
                    "timeout_seconds": timeout,
                },
            )
            duration_ms_value = duration_ms if duration_ms is not None else 0

            # Emit error event if handler provided
            if event_handler:
                await event_handler(
                    "error",
                    {
                        "error": error_msg,
                        "isPermanent": True,
                    },
                )

            return {
                "success": False,
                "cost_usd": cost_usd,
                "duration_ms": duration_ms_value,
                "error": error_msg,
            }
        except asyncio.CancelledError:
            logger.info(
                "Agent run cancelled",
                extra={
                    "run_label": run_label,
                    "command_name": command_name,
                },
            )
            raise
        except Exception as e:
            logger.exception(
                "Agent processing failed with exception",
                extra={
                    "run_label": run_label,
                    "command_name": command_name,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            duration_ms_value = duration_ms if duration_ms is not None else 0

            # Emit error event if handler provided
            if event_handler:
                await event_handler(
                    "error",
                    {
                        "error": str(e),
                        "isPermanent": True,
                    },
                )

            return {
                "success": False,
                "cost_usd": cost_usd,
                "duration_ms": duration_ms_value,
                "error": str(e),
            }

    async def run_command(
        self,
        command_name: str,
        *,
        arguments: str | None = None,
        max_budget_usd: float | None = None,
        timeout_seconds: int | None = None,
        model: str | None = None,
        event_handler: Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]] | None = None,
    ) -> ProcessResult:
        """
        Run a slash command from the vault commands directory.

        Args:
            command_name: Name of the command to run
            arguments: Optional arguments string
            max_budget_usd: Optional budget override
            timeout_seconds: Optional timeout override
            model: Optional model override
            event_handler: Optional async callback for events (event_type, data)

        Returns:
            ProcessResult with success status, cost, duration, and error
        """
        prompt = f"/{command_name}"
        if arguments:
            prompt = f"{prompt} {arguments}"

        return await self._run_prompt(
            prompt,
            run_label="scheduled_command",
            command_name=command_name,
            max_budget_usd=max_budget_usd,
            timeout_seconds=timeout_seconds,
            model=model,
            event_handler=event_handler,
        )
