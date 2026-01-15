"""API endpoints for accessing Claude Code session logs."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.dependencies import (
    get_agent_session_manager,
    get_chat_title_service,
    get_claude_session_api,
)
from app.services.agent_session_manager import AgentSessionManager
from app.services.chat_titles import ChatTitleService
from app.services.claude_session_api import ClaudeSessionAPI
from app.utils.claude_session_pagination import paginate_sessions
from app.utils.pagination import PaginationError
from app.utils.path_validation import PathValidationError, validate_session_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/claude-sessions", tags=["claude-sessions"])


class SessionListItem(BaseModel):
    """Response model for session list items."""

    model_config = ConfigDict(extra="allow")

    session_id: str
    title: str | None
    summary: str | None
    is_agent_session: bool
    created_at: str | None
    last_activity: str | None
    message_count: int
    file_path: str
    is_running: bool


class SessionListResponse(BaseModel):
    """Response model for session list."""

    sessions: list[SessionListItem]
    total: int
    next_cursor: str | None = None
    has_more: bool = False


class SessionDetailResponse(BaseModel):
    """Response model for session detail."""

    session_id: str
    title: str | None
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
    cursor: str | None = Query(None, description="Opaque cursor for pagination"),
    claude_session_api: ClaudeSessionAPI = Depends(get_claude_session_api),
    agent_session_manager: AgentSessionManager = Depends(get_agent_session_manager),
    chat_title_service: ChatTitleService = Depends(get_chat_title_service),
) -> SessionListResponse | JSONResponse:
    """
    List available Claude Code sessions.

    Returns sessions ordered by last activity (newest first).
    Can optionally include agent/sidechain sessions and search by summary.

    Args:
        include_agent_sessions: Whether to include agent sessions
        limit: Maximum number of sessions to return
        query: Optional search query for filtering by summary
        cursor: Optional opaque cursor for pagination

    Returns:
        List of session metadata
    """
    if query:
        sessions = claude_session_api.search_sessions(
            query=query,
            include_agent_sessions=include_agent_sessions,
            limit=None,
        )
    else:
        sessions = claude_session_api.list_sessions(
            include_agent_sessions=include_agent_sessions,
            limit=None,
        )

    try:
        page, next_cursor = paginate_sessions(sessions, limit, cursor)
    except PaginationError as exc:
        logger.warning(
            "Invalid Claude sessions cursor",
            extra={"cursor": cursor, "error": str(exc)},
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "InvalidCursor", "message": str(exc)},
        )

    running_ids = await agent_session_manager.get_running_session_ids()
    titles = await chat_title_service.get_titles([session["session_id"] for session in page])
    session_items: list[SessionListItem] = []
    for session in page:
        session_id = session.get("session_id")
        title = titles.get(session_id) if isinstance(session_id, str) else None
        is_running = session_id in running_ids if isinstance(session_id, str) else False
        session_items.append(
            SessionListItem(
                **{
                    **session,
                    "title": title or session.get("summary") or None,
                    "is_running": is_running,
                }
            )
        )

    has_more = next_cursor is not None
    logger.info(
        "Listed Claude sessions",
        extra={
            "returned_count": len(page),
            "limit": limit,
            "has_more": has_more,
        },
    )

    return SessionListResponse(
        sessions=session_items,
        total=len(page),
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(
    session_id: str = Path(..., description="Session UUID or agent ID"),
    claude_session_api: ClaudeSessionAPI = Depends(get_claude_session_api),
    chat_title_service: ChatTitleService = Depends(get_chat_title_service),
) -> SessionDetailResponse:
    """
    Get complete session data including all messages.

    Args:
        session_id: Session UUID or agent ID (e.g., 'agent-a1917ad')

    Returns:
        Complete session data with messages

    Raises:
        HTTPException: If session not found (404) or invalid (400)
    """
    # Validate session_id format to prevent path traversal
    try:
        validated_id = validate_session_id(session_id)
    except PathValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid session ID: {e}",
        )

    session = claude_session_api.get_session(validated_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {validated_id} not found",
        )

    logger.info(
        "Retrieved Claude session %s with %d messages", validated_id, session["message_count"]
    )

    title = await chat_title_service.get_title(validated_id)
    return SessionDetailResponse(
        **{
            **session,
            "title": title or session.get("summary") or None,
        }
    )


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
        HTTPException: If session not found (404) or invalid (400)
    """
    # Validate session_id format to prevent path traversal
    try:
        validated_id = validate_session_id(session_id)
    except PathValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid session ID: {e}",
        )

    # Verify session exists
    summary = claude_session_api.get_session_summary(validated_id)
    if not summary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {validated_id} not found",
        )

    messages = claude_session_api.get_session_messages(validated_id, roles=roles)

    logger.info("Retrieved %d messages from Claude session %s", len(messages), validated_id)

    return MessageListResponse(
        session_id=validated_id,
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
        HTTPException: If session not found (404) or invalid (400)
    """
    # Validate session_id format to prevent path traversal
    try:
        validated_id = validate_session_id(session_id)
    except PathValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid session ID: {e}",
        )

    summary = claude_session_api.get_session_summary(validated_id)

    if not summary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {validated_id} not found",
        )

    return summary
