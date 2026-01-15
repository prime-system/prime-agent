from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings  # This is now a dynamic proxy
from app.services.container import get_container

if TYPE_CHECKING:
    from app.services.agent import AgentService
    from app.services.agent_chat import AgentChatService
    from app.services.agent_identity import AgentIdentityService
    from app.services.agent_session_manager import AgentSessionManager
    from app.services.chat_session_manager import ChatSessionManager
    from app.services.chat_titles import ChatTitleService
    from app.services.claude_session_api import ClaudeSessionAPI
    from app.services.command_run_manager import CommandRunManager
    from app.services.git import GitService
    from app.services.health import HealthCheckService
    from app.services.inbox import InboxService
    from app.services.logs import LogService
    from app.services.push_notifications import PushNotificationService
    from app.services.relay_client import PrimePushRelayClient
    from app.services.schedule import ScheduleService
    from app.services.vault import VaultService
    from app.services.vault_browser import VaultBrowserService

security = HTTPBearer(auto_error=False)


async def verify_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> None:
    """
    Verify the bearer token matches configured AUTH_TOKEN.

    Uses the dynamic settings proxy to get the current auth_token,
    which may have been reloaded from config.yaml.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    if credentials.credentials != settings.auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )


async def get_vault_service() -> VaultService:
    """Get vault service via dependency injection."""
    container = get_container()
    return container.vault_service


async def get_vault_browser_service() -> VaultBrowserService:
    """Get vault browser service via dependency injection."""
    container = get_container()
    return container.vault_browser_service


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


async def get_chat_title_service() -> ChatTitleService:
    """Get chat title service via dependency injection."""
    container = get_container()
    return container.chat_title_service


async def get_relay_client() -> PrimePushRelayClient:
    """Get PrimePushRelay client via dependency injection."""
    container = get_container()
    return container.relay_client


async def get_push_notification_service() -> PushNotificationService:
    """Get push notification service via dependency injection."""
    container = get_container()
    return container.push_notification_service


async def get_claude_session_api() -> ClaudeSessionAPI:
    """Get Claude session API via dependency injection."""
    container = get_container()
    return container.claude_session_api


async def get_health_service() -> HealthCheckService:
    """Get health check service via dependency injection."""
    container = get_container()
    return container.health_service


async def get_agent_identity_service() -> AgentIdentityService:
    """Get agent identity service via dependency injection."""
    container = get_container()
    return container.agent_identity_service


async def get_schedule_service() -> ScheduleService:
    """Get schedule service via dependency injection."""
    container = get_container()
    return container.schedule_service


async def get_command_run_manager() -> CommandRunManager:
    """Get command run manager via dependency injection."""
    container = get_container()
    return container.command_run_manager
