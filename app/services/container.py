"""
Service dependency container.

Centralizes service creation and access without global state mutation.
Replaces the anti-pattern of module-level globals found in API modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.agent import AgentService
    from app.services.agent_chat import AgentChatService
    from app.services.agent_identity import AgentIdentityService
    from app.services.agent_session_manager import AgentSessionManager
    from app.services.chat_session_manager import ChatSessionManager
    from app.services.claude_session_api import ClaudeSessionAPI
    from app.services.command import CommandService
    from app.services.git import GitService
    from app.services.health import HealthCheckService
    from app.services.inbox import InboxService
    from app.services.logs import LogService
    from app.services.push_notifications import PushNotificationService
    from app.services.relay_client import PrimePushRelayClient
    from app.services.vault import VaultService
    from app.services.vault_browser import VaultBrowserService


class ServiceContainer:
    """Container for all application services.

    Provides centralized access to services without global state mutation.
    Services are injected via FastAPI's Depends() mechanism.
    """

    def __init__(
        self,
        vault_service: VaultService,
        vault_browser_service: VaultBrowserService,
        git_service: GitService,
        inbox_service: InboxService,
        agent_service: AgentService,
        log_service: LogService,
        chat_session_manager: ChatSessionManager,
        agent_chat_service: AgentChatService,
        agent_session_manager: AgentSessionManager,
        push_notification_service: PushNotificationService,
        relay_client: PrimePushRelayClient,
        claude_session_api: ClaudeSessionAPI,
        health_service: HealthCheckService,
        command_service: CommandService,
        agent_identity_service: AgentIdentityService,
    ) -> None:
        """Initialize service container with all required services."""
        self.vault_service = vault_service
        self.vault_browser_service = vault_browser_service
        self.git_service = git_service
        self.inbox_service = inbox_service
        self.agent_service = agent_service
        self.log_service = log_service
        self.chat_session_manager = chat_session_manager
        self.agent_chat_service = agent_chat_service
        self.agent_session_manager = agent_session_manager
        self.push_notification_service = push_notification_service
        self.relay_client = relay_client
        self.claude_session_api = claude_session_api
        self.health_service = health_service
        self.command_service = command_service
        self.agent_identity_service = agent_identity_service


_container: ServiceContainer | None = None


def init_container(
    vault_service: VaultService,
    git_service: GitService,
    inbox_service: InboxService,
    agent_service: AgentService,
    log_service: LogService,
    chat_session_manager: ChatSessionManager,
    agent_chat_service: AgentChatService,
    agent_session_manager: AgentSessionManager,
    push_notification_service: PushNotificationService,
    relay_client: PrimePushRelayClient,
    claude_session_api: ClaudeSessionAPI,
    health_service: HealthCheckService,
    command_service: CommandService,
    agent_identity_service: AgentIdentityService,
    vault_browser_service: VaultBrowserService | None = None,
) -> None:
    """Initialize service container (called once in FastAPI lifespan).

    Args:
        vault_service: VaultService instance for vault operations
        vault_browser_service: VaultBrowserService instance for browsing files
        git_service: GitService instance for git operations
        inbox_service: InboxService instance for capture formatting
        agent_service: AgentService instance for agent operations
        log_service: LogService instance for audit logging
        chat_session_manager: ChatSessionManager for managing chat sessions
        agent_chat_service: AgentChatService for agent chat operations
        agent_session_manager: AgentSessionManager for managing agent sessions
        push_notification_service: PushNotificationService for push notifications
        relay_client: PrimePushRelayClient for push notifications
        claude_session_api: ClaudeSessionAPI for Claude session access
        health_service: HealthCheckService for health checks
        command_service: CommandService for managing slash commands
        agent_identity_service: AgentIdentityService for persistent agent ID
    """
    global _container

    if vault_browser_service is None:
        from app.services.vault_browser import VaultBrowserService

        vault_browser_service = VaultBrowserService(vault_service=vault_service)

    _container = ServiceContainer(
        vault_service=vault_service,
        vault_browser_service=vault_browser_service,
        git_service=git_service,
        inbox_service=inbox_service,
        agent_service=agent_service,
        log_service=log_service,
        chat_session_manager=chat_session_manager,
        agent_chat_service=agent_chat_service,
        agent_session_manager=agent_session_manager,
        push_notification_service=push_notification_service,
        relay_client=relay_client,
        claude_session_api=claude_session_api,
        health_service=health_service,
        command_service=command_service,
        agent_identity_service=agent_identity_service,
    )


def get_container() -> ServiceContainer:
    """Get service container (use via FastAPI Depends).

    Returns:
        ServiceContainer with all initialized services

    Raises:
        RuntimeError: If container not initialized (lifespan not running)
    """
    if _container is None:
        msg = "Service container not initialized - application lifespan may not be running"
        raise RuntimeError(msg)
    return _container
