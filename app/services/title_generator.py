"""Service for generating titles from capture text using Claude."""

import logging
import re

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from app.config import settings

logger = logging.getLogger(__name__)


class TitleGenerator:
    """Generates short titles from capture text using Claude."""

    # JSON Schema for structured output - guarantees valid title format
    TITLE_SCHEMA = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "pattern": "^[a-z0-9-]+$",  # Only lowercase, numbers, hyphens
                "maxLength": 50,
            }
        },
        "required": ["title"],
    }

    def __init__(self):
        self.anthropic_api_key = settings.anthropic_api_key

    async def generate_title(self, text: str, max_length: int = 50) -> str:
        """
        Generate a short, filesystem-safe title from capture text using Claude.

        Uses structured outputs to guarantee valid JSON response with proper formatting.

        Args:
            text: The captured text to generate a title from
            max_length: Maximum length of the generated title

        Returns:
            A short, filesystem-safe title (lowercase, hyphens, no special chars)
        """
        try:
            prompt = f"""Generate a very short, descriptive title (3-6 words max) for this note:

{text}

Requirements:
- Keep it under {max_length} characters
- Use lowercase with hyphens instead of spaces
- No special characters or punctuation
- Be descriptive but concise

Example: "meeting-notes-with-team" or "grocery-shopping-list"
"""

            # Build environment dict for API authentication (matching agent.py pattern)
            env_dict = {"ANTHROPIC_API_KEY": self.anthropic_api_key}
            if settings.anthropic_base_url:
                env_dict["ANTHROPIC_BASE_URL"] = settings.anthropic_base_url

            # Configure options with structured output for guaranteed valid format
            options = ClaudeAgentOptions(
                output_format={
                    "type": "json_schema",
                    "schema": self.TITLE_SCHEMA,
                },
                model="haiku",  # Fast, cheap model for title generation
                env=env_dict,
            )

            # Iterate through messages and extract structured output
            title_result = None
            message_generator = query(prompt=prompt, options=options)
            try:
                async for message in message_generator:
                    if isinstance(message, ResultMessage):
                        # ResultMessage contains the final structured output
                        if hasattr(message, "structured_output") and message.structured_output:
                            title_result = message.structured_output.get("title", "")
                            # Exit after getting the result - generator will be explicitly closed
                            break
            finally:
                # Explicitly close the generator to ensure proper cleanup
                await message_generator.aclose()

            # Extract result after generator finishes
            if title_result and len(title_result) >= 3:
                return title_result[:max_length].rstrip("-")

            # Fallback if no title was generated
            return self._fallback_title(text, max_length)

        except Exception as e:
            logger.error(f"Failed to generate title: {e}")
            # Fallback to a simple sanitized version of the first few words
            return self._fallback_title(text, max_length)

    def _sanitize_title(self, title: str) -> str:
        """Make title filesystem-safe."""
        # Remove quotes and extra whitespace
        title = title.strip().strip('"').strip("'")

        # Replace spaces with hyphens
        title = title.replace(" ", "-")

        # Remove any characters that aren't alphanumeric, hyphens, or underscores
        title = re.sub(r"[^a-z0-9-_]", "", title)

        # Replace multiple consecutive hyphens with a single hyphen
        title = re.sub(r"-+", "-", title)

        # Remove leading/trailing hyphens
        title = title.strip("-")

        return title

    def _fallback_title(self, text: str, max_length: int) -> str:
        """Generate a simple fallback title from the first few words."""
        # Take first 50 chars, split into words, take first 3-4 words
        words = text[:100].lower().split()[:4]
        title = "-".join(words)

        # Sanitize
        title = self._sanitize_title(title)

        # Truncate if needed
        if len(title) > max_length:
            title = title[:max_length].rstrip("-")

        return title if title else "untitled"
