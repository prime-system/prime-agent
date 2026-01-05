"""
Request context management using ContextVars.

Provides request ID tracking across async boundaries for log correlation.
"""

from __future__ import annotations

import contextvars
import uuid
from typing import Optional

# Context variable for request ID
request_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_id",
    default=None,
)


def get_request_id() -> Optional[str]:
    """Get current request ID from context."""
    return request_id_var.get()


def set_request_id(request_id: str) -> None:
    """Set request ID in context."""
    request_id_var.set(request_id)


def generate_request_id() -> str:
    """Generate a new unique request ID."""
    return str(uuid.uuid4())


def clear_request_id() -> None:
    """Clear request ID from context."""
    request_id_var.set(None)
