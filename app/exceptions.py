"""
Custom exception classes with context for Prime Agent.

All exceptions inherit from PrimeAgentError base class and support
attaching contextual information for better debugging and logging.
"""

from __future__ import annotations


class PrimeAgentError(Exception):
    """
    Base exception for Prime Agent.

    All custom exceptions should inherit from this class to enable
    consistent error handling across the application.

    Attributes:
        message: Human-readable error message
        context: Optional dictionary with additional context for logging/debugging
    """

    def __init__(self, message: str, context: dict[str, object] | None = None):
        """
        Initialize exception with message and optional context.

        Args:
            message: Human-readable error message
            context: Optional dictionary with contextual information
                    (operation name, file paths, error details, etc.)
        """
        super().__init__(message)
        self.context = context or {}


class VaultError(PrimeAgentError):
    """
    Vault operation failed.

    Raised when filesystem operations, path resolution, or vault
    configuration operations fail.

    Example:
        raise VaultError(
            "Failed to create inbox directory",
            context={
                "operation": "create_inbox",
                "path": "/vault/.prime/inbox",
                "permissions": "755"
            }
        )
    """


class GitError(PrimeAgentError):
    """
    Git operation failed.

    Raised when git commands (clone, pull, commit, push) fail.

    Example:
        raise GitError(
            "Failed to push changes",
            context={
                "operation": "push",
                "remote": "origin",
                "branch": "main",
                "exit_code": 128
            }
        )
    """


class AgentError(PrimeAgentError):
    """
    Agent processing failed.

    Raised when Claude Agent SDK processing encounters an error.

    Example:
        raise AgentError(
            "Agent timeout during processing",
            context={
                "operation": "run_command",
                "timeout_seconds": 300,
                "cost_usd": 1.23
            }
        )
    """


class ConfigurationError(PrimeAgentError):
    """
    Configuration error.

    Raised when configuration loading, validation, or parsing fails.

    Example:
        raise ConfigurationError(
            "Missing required configuration key",
            context={
                "key": "anthropic.api_key",
                "config_file": "/app/config.yaml"
            }
        )
    """


class ValidationError(PrimeAgentError):
    """
    Input validation failed.

    Raised when request validation, data validation, or schema
    validation fails.

    Example:
        raise ValidationError(
            "Invalid capture source",
            context={
                "field": "source",
                "value": "invalid_device",
                "allowed_values": ["iphone", "ipad", "mac"]
            }
        )
    """


class InboxError(PrimeAgentError):
    """
    Inbox operation failed.

    Raised when inbox file operations (writing captures, formatting)
    encounter errors.

    Example:
        raise InboxError(
            "Failed to write capture file",
            context={
                "operation": "write_capture",
                "dump_id": "2026-01-05T12:00:00Z-iphone",
                "path": ".prime/inbox/capture.md"
            }
        )
    """


class TitleGenerationError(PrimeAgentError):
    """
    Title generation failed.

    Raised when Claude API fails to generate a title for a capture.

    Example:
        raise TitleGenerationError(
            "Claude API request failed",
            context={
                "operation": "generate_title",
                "api_error": "rate_limit_exceeded",
                "text_length": 500
            }
        )
    """
