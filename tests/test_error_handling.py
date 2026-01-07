"""
Tests for error handling and custom exceptions.

Verifies that custom exceptions include proper context and that
error handling utilities work correctly.
"""

from __future__ import annotations

import asyncio

import pytest

from app.exceptions import (
    AgentError,
    ConfigurationError,
    GitError,
    InboxError,
    PrimeAgentError,
    TitleGenerationError,
    ValidationError,
    VaultError,
)
from app.utils.error_handling import format_exception_for_response, log_errors, with_error_context


class TestCustomExceptions:
    """Test custom exception classes."""

    def test_prime_agent_error_base(self) -> None:
        """Base exception includes message and context."""
        error = PrimeAgentError(
            "Test error",
            context={"operation": "test", "value": 123},
        )

        assert str(error) == "Test error"
        assert error.context == {"operation": "test", "value": 123}

    def test_prime_agent_error_without_context(self) -> None:
        """Base exception works without context."""
        error = PrimeAgentError("Test error")

        assert str(error) == "Test error"
        assert error.context == {}

    def test_git_error_with_context(self) -> None:
        """GitError includes context."""
        context = {
            "operation": "push",
            "repo_path": "/vault",
            "branch": "main",
        }
        error = GitError("Push failed", context=context)

        assert str(error) == "Push failed"
        assert error.context == context
        assert isinstance(error, PrimeAgentError)

    def test_vault_error_with_context(self) -> None:
        """VaultError includes context."""
        context = {
            "operation": "create_inbox",
            "path": "/vault/.prime/inbox",
        }
        error = VaultError("Failed to create directory", context=context)

        assert str(error) == "Failed to create directory"
        assert error.context == context
        assert isinstance(error, PrimeAgentError)

    def test_agent_error_with_context(self) -> None:
        """AgentError includes context."""
        context = {
            "operation": "process_dumps",
            "timeout_seconds": 300,
            "cost_usd": 1.23,
        }
        error = AgentError("Processing timeout", context=context)

        assert str(error) == "Processing timeout"
        assert error.context == context
        assert isinstance(error, PrimeAgentError)

    def test_configuration_error(self) -> None:
        """ConfigurationError includes context."""
        context = {
            "key": "anthropic.api_key",
            "config_file": "/app/config.yaml",
        }
        error = ConfigurationError("Missing required key", context=context)

        assert str(error) == "Missing required key"
        assert error.context == context

    def test_validation_error(self) -> None:
        """ValidationError includes context."""
        context = {
            "field": "source",
            "value": "invalid",
            "allowed_values": ["iphone", "ipad", "mac"],
        }
        error = ValidationError("Invalid source", context=context)

        assert str(error) == "Invalid source"
        assert error.context == context

    def test_inbox_error(self) -> None:
        """InboxError includes context."""
        context = {
            "operation": "write_capture",
            "dump_id": "2026-01-05T12:00:00Z-iphone",
        }
        error = InboxError("Write failed", context=context)

        assert str(error) == "Write failed"
        assert error.context == context

    def test_title_generation_error(self) -> None:
        """TitleGenerationError includes context."""
        context = {
            "operation": "generate_title",
            "api_error": "rate_limit_exceeded",
        }
        error = TitleGenerationError("API request failed", context=context)

        assert str(error) == "API request failed"
        assert error.context == context


class TestErrorHandlingUtilities:
    """Test error handling utility functions."""

    def test_format_exception_for_response_with_context(self) -> None:
        """Format custom exception with context."""
        error = GitError(
            "Push failed",
            context={"operation": "push", "branch": "main"},
        )

        result = format_exception_for_response(error)

        assert result == {
            "error": "GitError",
            "message": "Push failed",
            "context": {"operation": "push", "branch": "main"},
        }

    def test_format_exception_for_response_without_context(self) -> None:
        """Format custom exception without context."""
        error = GitError("Push failed")

        result = format_exception_for_response(error)

        assert result == {
            "error": "GitError",
            "message": "Push failed",
        }

    def test_format_exception_for_response_generic_exception(self) -> None:
        """Format generic exception."""
        error = ValueError("Invalid value")

        result = format_exception_for_response(error)

        assert result == {
            "error": "ValueError",
            "message": "Invalid value",
        }

    def test_with_error_context_success(self) -> None:
        """Execute function successfully with error context."""

        def successful_operation() -> int:
            return 42

        result = with_error_context(
            successful_operation,
            operation="test_operation",
            context={"key": "value"},
        )

        assert result == 42

    def test_with_error_context_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        """Log error context when function fails."""

        def failing_operation() -> None:
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            with_error_context(
                failing_operation,
                operation="test_operation",
                context={"key": "value"},
            )

        # Verify logging
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert "Error in test_operation" in record.message
        assert record.operation == "test_operation"  # type: ignore[attr-defined]
        assert record.error_type == "ValueError"  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_log_errors_decorator_async_success(self) -> None:
        """Decorator doesn't interfere with successful async function."""

        @log_errors("test_async_operation")
        async def successful_async() -> str:
            await asyncio.sleep(0.01)
            return "success"

        result = await successful_async()
        assert result == "success"

    @pytest.mark.asyncio
    async def test_log_errors_decorator_async_failure(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Decorator logs errors from async functions."""

        @log_errors("test_async_operation")
        async def failing_async() -> None:
            await asyncio.sleep(0.01)
            raise ValueError("Async error")

        with pytest.raises(ValueError, match="Async error"):
            await failing_async()

        # Verify logging
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert "Error in test_async_operation" in record.message
        assert record.operation == "test_async_operation"  # type: ignore[attr-defined]
        assert record.function == "failing_async"  # type: ignore[attr-defined]

    def test_log_errors_decorator_sync_success(self) -> None:
        """Decorator doesn't interfere with successful sync function."""

        @log_errors("test_sync_operation")
        def successful_sync() -> int:
            return 123

        result = successful_sync()
        assert result == 123

    def test_log_errors_decorator_sync_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        """Decorator logs errors from sync functions."""

        @log_errors("test_sync_operation")
        def failing_sync() -> None:
            raise ValueError("Sync error")

        with pytest.raises(ValueError, match="Sync error"):
            failing_sync()

        # Verify logging
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert "Error in test_sync_operation" in record.message
        assert record.operation == "test_sync_operation"  # type: ignore[attr-defined]
        assert record.function == "failing_sync"  # type: ignore[attr-defined]


class TestExceptionChaining:
    """Test exception chaining preserves context."""

    def test_exception_chaining_preserves_cause(self) -> None:
        """Verify exception chaining with 'from' preserves original."""
        try:
            try:
                raise OSError("File not found")
            except OSError as e:
                raise GitError(
                    "Git operation failed",
                    context={"operation": "clone"},
                ) from e
        except GitError as git_error:
            assert str(git_error) == "Git operation failed"
            assert git_error.context == {"operation": "clone"}
            assert isinstance(git_error.__cause__, OSError)
            assert str(git_error.__cause__) == "File not found"

    def test_exception_chaining_in_nested_operations(self) -> None:
        """Verify nested exception chaining."""
        try:
            try:
                try:
                    raise ValueError("Invalid config")
                except ValueError as e:
                    raise ConfigurationError(
                        "Config parsing failed",
                        context={"file": "config.yaml"},
                    ) from e
            except ConfigurationError as e:
                raise VaultError(
                    "Vault initialization failed",
                    context={"operation": "initialize"},
                ) from e
        except VaultError as vault_error:
            # Check top-level exception
            assert str(vault_error) == "Vault initialization failed"
            assert vault_error.context == {"operation": "initialize"}

            # Check intermediate exception
            assert isinstance(vault_error.__cause__, ConfigurationError)
            config_error = vault_error.__cause__
            assert str(config_error) == "Config parsing failed"
            assert config_error.context == {"file": "config.yaml"}

            # Check root cause
            assert isinstance(config_error.__cause__, ValueError)
            assert str(config_error.__cause__) == "Invalid config"
