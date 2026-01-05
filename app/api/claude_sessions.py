"""API endpoints for accessing Claude Code session logs."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel

from app.dependencies import get_claude_session_api
from app.services.claude_session_api import ClaudeSessionAPI

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/claude-sessions", tags=["claude-sessions"])


class SessionListResponse(BaseModel):
    """Response model for session list."""

    sessions: list[dict[str, Any]]
    total: int


class SessionDetailResponse(BaseModel):
    """Response model for session detail."""

    session_id: str
    summary: str | None
    is_agent_session: bool
    created_at: str | None
    last_activity: str | None
    message_count: int
    messages: list[dict[str, Any]]


class MessageListResponse(BaseModel):
    """Response model for message list."""

    session_id: str
    messages: list[dict[str, Any]]
    message_count: int


@router.get("/", response_model=SessionListResponse)
async def list_sessions(
    include_agent_sessions: bool = Query(
        False,
        description="Include agent/sidechain sessions",
    ),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of sessions"),
    query: str | None = Query(None, description="Search query for session summaries"),
    claude_session_api: ClaudeSessionAPI = Depends(get_claude_session_api),
) -> SessionListResponse:
    """
    List available Claude Code sessions.

    Returns sessions ordered by last activity (newest first).
    Can optionally include agent/sidechain sessions and search by summary.

    Args:
        include_agent_sessions: Whether to include agent sessions
        limit: Maximum number of sessions to return
        query: Optional search query for filtering by summary

    Returns:
        List of session metadata
    """
    if query:
        sessions = claude_session_api.search_sessions(
            query=query,
            include_agent_sessions=include_agent_sessions,
            limit=limit,
        )
    else:
        sessions = claude_session_api.list_sessions(
            include_agent_sessions=include_agent_sessions,
            limit=limit,
        )

    logger.info("Listed %d Claude sessions", len(sessions))

    return SessionListResponse(
        sessions=sessions,
        total=len(sessions),
    )


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(
    session_id: str = Path(..., description="Session UUID or agent ID"),
    claude_session_api: ClaudeSessionAPI = Depends(get_claude_session_api),
) -> SessionDetailResponse:
    """
    Get complete session data including all messages.

    Args:
        session_id: Session UUID or agent ID (e.g., 'agent-a1917ad')

    Returns:
        Complete session data with messages

    Raises:
        HTTPException: If session not found (404)
    """
    session = claude_session_api.get_session(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    logger.info("Retrieved Claude session %s with %d messages", session_id, session["message_count"])

    return SessionDetailResponse(**session)


@router.get("/{session_id}/messages", response_model=MessageListResponse)
async def get_session_messages(
    session_id: str = Path(..., description="Session UUID or agent ID"),
    roles: list[str] | None = Query(
        None,
        description="Filter messages by role (user, assistant)",
    ),
    claude_session_api: ClaudeSessionAPI = Depends(get_claude_session_api),
) -> MessageListResponse:
    """
    Get messages from a session, optionally filtered by role.

    Returns only user and assistant messages (excludes system messages).

    Args:
        session_id: Session UUID or agent ID
        roles: Optional list of roles to include

    Returns:
        List of messages

    Raises:
        HTTPException: If session not found (404)
    """
    # Verify session exists
    summary = claude_session_api.get_session_summary(session_id)
    if not summary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    messages = claude_session_api.get_session_messages(session_id, roles=roles)

    logger.info("Retrieved %d messages from Claude session %s", len(messages), session_id)

    return MessageListResponse(
        session_id=session_id,
        messages=messages,
        message_count=len(messages),
    )


@router.get("/{session_id}/summary")
async def get_session_summary(
    session_id: str = Path(..., description="Session UUID or agent ID"),
    claude_session_api: ClaudeSessionAPI = Depends(get_claude_session_api),
) -> dict[str, Any]:
    """
    Get session metadata without loading all messages.

    Lightweight endpoint for getting session info quickly.

    Args:
        session_id: Session UUID or agent ID

    Returns:
        Session metadata

    Raises:
        HTTPException: If session not found (404)
    """
    summary = claude_session_api.get_session_summary(session_id)

    if not summary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    return summary
