from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings  # This is now a dynamic proxy
from app.services.container import get_container

if TYPE_CHECKING:
    from app.services.agent import AgentService
    from app.services.agent_chat import AgentChatService
    from app.services.agent_session_manager import AgentSessionManager
    from app.services.apn_service import APNService
    from app.services.chat_session_manager import ChatSessionManager
    from app.services.claude_session_api import ClaudeSessionAPI
    from app.services.git import GitService
    from app.services.inbox import InboxService
    from app.services.logs import LogService
    from app.services.vault import VaultService

security = HTTPBearer()


async def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> None:
    """
    Verify the bearer token matches configured AUTH_TOKEN.

    Uses the dynamic settings proxy to get the current auth_token,
    which may have been reloaded from config.yaml.
    """
    if credentials.credentials != settings.auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )


async def get_vault_service() -> VaultService:
    """Get vault service via dependency injection."""
    container = get_container()
    return container.vault_service


async def get_git_service() -> GitService:
    """Get git service via dependency injection."""
    container = get_container()
    return container.git_service


async def get_inbox_service() -> InboxService:
    """Get inbox service via dependency injection."""
    container = get_container()
    return container.inbox_service


async def get_agent_service() -> AgentService:
    """Get agent service via dependency injection."""
    container = get_container()
    return container.agent_service


async def get_log_service() -> LogService:
    """Get log service via dependency injection."""
    container = get_container()
    return container.log_service


async def get_chat_session_manager() -> ChatSessionManager:
    """Get chat session manager via dependency injection."""
    container = get_container()
    return container.chat_session_manager


async def get_agent_chat_service() -> AgentChatService:
    """Get agent chat service via dependency injection."""
    container = get_container()
    return container.agent_chat_service


async def get_agent_session_manager() -> AgentSessionManager:
    """Get agent session manager via dependency injection."""
    container = get_container()
    return container.agent_session_manager


async def get_apn_service() -> APNService | None:
    """Get APN service via dependency injection (may be None if disabled)."""
    container = get_container()
    return container.apn_service


async def get_claude_session_api() -> ClaudeSessionAPI:
    """Get Claude session API via dependency injection."""
    container = get_container()
    return container.claude_session_api
