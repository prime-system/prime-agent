"""
Agent service for processing dumps using Claude Agent SDK.

This module provides the core integration with the Claude Agent SDK,
managing the transformation of raw brain dumps into structured knowledge.
"""

import asyncio
import logging
from pathlib import Path
from typing import TypedDict

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from app.exceptions import AgentError
from app.utils.frontmatter import (
    FrontmatterError,
    parse_and_validate_command,
    strip_frontmatter,
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
    Manages Claude Agent SDK invocation for dump processing.

    The agent reads unprocessed dumps from Inbox/, transforms them into
    structured knowledge, and writes to Daily/, Notes/, Projects/, Tasks/,
    and Questions/ folders.
    """

    def __init__(
        self,
        vault_path: str,
        api_key: str,
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
            api_key: Anthropic API key
            base_url: Optional custom API endpoint
            prime_api_url: Prime API base URL for notify skill
            prime_api_token: Prime API auth token for notify skill
            max_budget_usd: Maximum cost per processing run (safety limit)
            timeout_seconds: Timeout for agent processing in seconds
        """
        self.vault_path = Path(vault_path)
        self.api_key = api_key
        self.base_url = base_url
        self.prime_api_url = prime_api_url
        self.prime_api_token = prime_api_token
        self.max_budget_usd = max_budget_usd
        self.timeout_seconds = timeout_seconds

    def _get_process_capture_prompt(self) -> str:
        """
        Get the prompt for processing captures.

        If processCapture command exists in vault (.claude/commands/processCapture.md),
        returns "/processCapture" to invoke it as a slash command.
        Otherwise, loads and returns the template content from source code.

        Returns:
            Either "/processCapture" slash command or template content string
        """
        # Check if custom command exists in vault
        vault_command_path = self.vault_path / ".claude" / "commands" / "processCapture.md"

        if vault_command_path.exists():
            # Use slash command - SDK will load it automatically
            logger.info(
                "Using processCapture command from vault",
                extra={
                    "command_path": str(vault_command_path),
                },
            )
            return "/processCapture"

        # Fall back to loading template content from source code
        template_path = Path(__file__).parent.parent / "prompts" / "processCapture.md"
        logger.info(
            "No vault command found, loading template",
            extra={
                "template_path": str(template_path),
            },
        )

        if not template_path.exists():
            msg = f"processCapture template not found: {template_path}"
            raise AgentError(
                msg,
                context={
                    "operation": "get_process_capture_prompt",
                    "template_path": str(template_path),
                    "vault_path": str(self.vault_path),
                },
            )

        command_content = template_path.read_text()

        # Strip YAML frontmatter using robust parser
        try:
            _, actual_content = parse_and_validate_command(command_content)
            actual_content = actual_content.strip()
        except FrontmatterError:
            # If parsing fails, try simple fallback
            actual_content = strip_frontmatter(command_content).strip()

        logger.debug(
            "Loaded template content",
            extra={
                "content_length": len(actual_content),
            },
        )
        return actual_content

    async def process_dumps(self) -> ProcessResult:
        """
        Process all unprocessed dumps using Claude Agent SDK.

        The agent will:
        1. Read all unprocessed dumps from Inbox/
        2. Transform them into structured knowledge
        3. Write to appropriate vault folders
        4. Mark dumps as processed

        Returns:
            Dictionary with processing results:
            {
                "success": bool,
                "cost_usd": Optional[float],
                "duration_ms": int,
                "error": Optional[str]
            }
        """
        logger.info("Starting agent processing")

        # Configure agent options
        # Build environment dict for API authentication
        env_dict = {"ANTHROPIC_API_KEY": self.api_key}
        if self.base_url:
            env_dict["ANTHROPIC_BASE_URL"] = self.base_url
        if self.prime_api_url:
            env_dict["PRIME_API_URL"] = self.prime_api_url.rstrip("/")
        if self.prime_api_token:
            env_dict["PRIME_API_TOKEN"] = self.prime_api_token

        options = ClaudeAgentOptions(
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
        )

        # Track results
        cost_usd: float | None = None
        duration_ms: int = 0
        error_msg: str | None = None

        async def _agent_processing() -> None:
            """Inner async function to stream messages from agent."""
            nonlocal cost_usd, duration_ms, error_msg

            # Get the prompt - either slash command or template content
            command_prompt = self._get_process_capture_prompt()

            # Stream messages from agent
            async for message in query(
                prompt=command_prompt,
                options=options,
            ):
                # Collect information from messages
                if isinstance(message, ResultMessage):
                    # Final result with cost and usage
                    cost_usd = message.total_cost_usd
                    duration_ms = message.duration_ms

                    # Check if processing was successful
                    if message.is_error:
                        error_msg = "Agent processing failed"
                        logger.error(
                            "Agent returned error",
                            extra={
                                "agent_message": str(message),
                            },
                        )

        try:
            # Wrap agent processing with timeout
            await asyncio.wait_for(_agent_processing(), timeout=self.timeout_seconds)

            # Return processing results
            # Note: Worker handles git commit/push after this returns
            return {
                "success": error_msg is None,
                "cost_usd": cost_usd,
                "duration_ms": duration_ms,
                "error": error_msg,
            }

        except TimeoutError:
            error_msg = f"Agent processing timed out after {self.timeout_seconds}s"
            logger.error(
                "Agent processing timed out",
                extra={
                    "timeout_seconds": self.timeout_seconds,
                },
            )
            return {
                "success": False,
                "cost_usd": None,
                "duration_ms": 0,
                "error": error_msg,
            }
        except Exception as e:
            logger.exception(
                "Agent processing failed with exception",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            return {
                "success": False,
                "cost_usd": None,
                "duration_ms": 0,
                "error": str(e),
            }
