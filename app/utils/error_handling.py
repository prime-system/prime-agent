"""
Error handling utilities for Prime Agent.

Provides decorators and helpers for consistent error handling and logging.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def log_errors(operation_name: str) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator to log errors with context.

    Automatically logs exceptions with structured context including
    operation name, function name, and error details. The exception
    is re-raised after logging.

    Args:
        operation_name: Name of the operation for logging context

    Returns:
        Decorated function that logs errors before re-raising

    Example:
        @log_errors("git_push")
        async def push_changes(repo: Repo) -> None:
            # If this raises, error is logged with context
            repo.push()
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logger.exception(
                    f"Error in {operation_name}",
                    extra={
                        "operation": operation_name,
                        "error_type": type(e).__name__,
                        "function": func.__name__,
                    },
                )
                raise

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.exception(
                    f"Error in {operation_name}",
                    extra={
                        "operation": operation_name,
                        "error_type": type(e).__name__,
                        "function": func.__name__,
                    },
                )
                raise

        if inspect.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator


def with_error_context(
    func: Callable[..., T],
    operation: str,
    context: dict[str, object],
) -> T:
    """
    Execute a function with error context logging.

    This is a functional alternative to the @log_errors decorator,
    useful when you can't use a decorator (e.g., lambda functions,
    dynamic operations).

    Args:
        func: Function to execute
        operation: Operation name for logging
        context: Additional context to include in logs

    Returns:
        Result from func execution

    Raises:
        Exception: Re-raises any exception after logging with context

    Example:
        result = with_error_context(
            lambda: repo.push(),
            operation="git_push",
            context={"repo_path": "/vault", "branch": "main"}
        )
    """
    try:
        return func()
    except Exception as e:
        logger.exception(
            f"Error in {operation}",
            extra={
                "operation": operation,
                "error_type": type(e).__name__,
                **context,
            },
        )
        raise


def format_exception_for_response(e: Exception) -> dict[str, object]:
    """
    Format exception for API error response.

    Extracts error message and context from custom exceptions
    or formats generic exceptions for HTTP responses.

    Args:
        e: Exception to format

    Returns:
        Dictionary with error details suitable for API response

    Example:
        try:
            do_something()
        except GitError as e:
            raise HTTPException(
                status_code=500,
                detail=format_exception_for_response(e)
            )
    """
    from app.exceptions import PrimeAgentError

    error_dict: dict[str, object] = {
        "error": type(e).__name__,
        "message": str(e),
    }

    # Add context if available
    if isinstance(e, PrimeAgentError) and e.context:
        error_dict["context"] = e.context

    return error_dict
