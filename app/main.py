import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    capture,
    chat,
    claude_sessions,
    commands,
    config,
    files,
    git,
    health,
    monitoring,
    push,
    schedule,
    vault_browser,
    vault_search,
)
from app.config import settings
from app.logging_config import configure_json_logging
from app.middleware.request_id import RequestIDMiddleware
from app.services import agent_identity, chat_titles, device_registry
from app.services.agent import AgentService
from app.services.agent_chat import AgentChatService
from app.services.agent_identity import AgentIdentityService
from app.services.agent_session_manager import AgentSessionManager
from app.services.chat_session_manager import ChatSessionManager
from app.services.chat_titles import ChatTitleService
from app.services.claude_session_api import ClaudeSessionAPI
from app.services.command import CommandService
from app.services.command_run_manager import CommandRunManager
from app.services.container import init_container
from app.services.git import GitService
from app.services.health import HealthCheckService
from app.services.inbox import InboxService
from app.services.lock import init_vault_lock
from app.services.logs import LogService
from app.services.push_notifications import PushNotificationService
from app.services.relay_client import PrimePushRelayClient
from app.services.schedule import ScheduleService
from app.services.vault import VaultService
from app.services.vault_browser import VaultBrowserService
from app.services.vault_search import VaultSearchService
from app.version import get_version

# Configure structured JSON logging
configure_json_logging(log_level=settings.log_level)
logger = logging.getLogger(__name__)

# Suppress known asyncio warning from Claude SDK task context issue
# The SDK creates cancel scopes in one task but they're exited in another
# This is a known SDK issue and doesn't affect functionality
asyncio_logger = logging.getLogger("asyncio")


class AsyncioErrorFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        """Suppress known asyncio cancel scope warning from Claude SDK."""
        return "Attempted to exit cancel scope in a different task" not in record.getMessage()


asyncio_logger.addFilter(AsyncioErrorFilter())


async def periodic_git_pull(git_service: GitService, interval_seconds: int = 300) -> None:
    """
    Background task to periodically pull changes from remote.

    Args:
        git_service: GitService instance
        interval_seconds: Interval between pulls (default: 5 minutes)
    """
    logger.info(f"Starting periodic git pull (interval: {interval_seconds}s)")

    while True:
        try:
            await asyncio.sleep(interval_seconds)

            if git_service.enabled:
                logger.debug("Running periodic git pull...")
                git_service.pull()
            else:
                logger.debug("Git disabled, skipping periodic pull")

        except asyncio.CancelledError:
            logger.info("Periodic git pull task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in periodic git pull: {e}")
            # Continue despite errors


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application startup and shutdown."""
    logger.info("Starting Prime server...")

    # Initialize async locks in the running event loop (MUST be first!)
    await init_vault_lock()
    await device_registry.init_file_lock()
    await agent_identity.init_file_lock()
    await chat_titles.init_file_lock()

    # Initialize services
    vault_service = VaultService(settings.vault_path)
    agent_identity_service = AgentIdentityService(Path(settings.data_path))
    await agent_identity_service.get_or_create_identity()  # Load/create at startup
    vault_browser_service = VaultBrowserService(vault_service=vault_service)
    vault_search_service = VaultSearchService(vault_service=vault_service)

    git_service = GitService(
        vault_path=settings.vault_path,
        enabled=settings.git_enabled,
        repo_url=settings.vault_repo_url,
        user_name=settings.git_user_name,
        user_email=settings.git_user_email,
        timeout_seconds=settings.git_timeout_seconds,
    )

    inbox_service = InboxService()

    prime_api_url = settings.base_url or "http://localhost:8000"

    # Initialize agent services
    agent_service = AgentService(
        vault_path=settings.vault_path,
        api_key=settings.anthropic_api_key,
        oauth_token=settings.anthropic_oauth_token,
        base_url=settings.anthropic_base_url,
        prime_api_url=prime_api_url,
        prime_api_token=settings.auth_token,
        max_budget_usd=settings.agent_max_budget_usd,
        timeout_seconds=settings.anthropic_timeout_seconds,
    )

    log_service = LogService(
        logs_dir=vault_service.logs_path(),
        vault_path=vault_service.vault_path,
        vault_service=vault_service,
    )

    # Initialize chat session manager (works directly with Claude sessions)
    chat_session_manager = ChatSessionManager(
        vault_path=settings.vault_path,
        claude_home="/home/prime/.claude",
    )

    # Initialize agent chat service
    agent_chat_service = AgentChatService(
        vault_path=settings.vault_path,
        model=settings.agent_model,
        api_key=settings.anthropic_api_key,
        oauth_token=settings.anthropic_oauth_token,
        base_url=settings.anthropic_base_url,
        prime_api_url=prime_api_url,
        prime_api_token=settings.auth_token,
        git_service=git_service,
    )

    # Initialize git repo (no-op if disabled) and vault structure
    git_service.initialize()
    vault_service.ensure_structure()

    # Initialize PrimePushRelay client
    relay_client = PrimePushRelayClient(timeout_seconds=10)

    # Initialize push notification service
    push_notification_service = PushNotificationService(
        devices_file=settings.apn_devices_file,
        relay_client=relay_client,
    )

    # Initialize chat title service
    chat_title_service = ChatTitleService(settings.chat_titles_file)

    # Initialize AgentSessionManager
    agent_session_manager = AgentSessionManager(
        agent_service=agent_chat_service,
        title_agent_service=agent_service,
        chat_title_service=chat_title_service,
        push_notification_service=push_notification_service,
    )
    agent_session_manager.start_cleanup_loop()

    # Initialize Claude session API
    claude_session_api = ClaudeSessionAPI(
        project_path=settings.vault_path,
        claude_home="/home/prime/.claude",
    )

    # Initialize health check service
    health_service = HealthCheckService(
        vault_service=vault_service,
        git_service=git_service,
        version=get_version(),
    )

    # Initialize command service
    command_service = CommandService(str(vault_service.vault_path))

    # Initialize schedule service
    schedule_service = ScheduleService(
        vault_path=str(vault_service.vault_path),
        agent_service=agent_service,
        command_service=command_service,
        chat_title_service=chat_title_service,
        git_service=git_service,
        log_service=log_service,
        vault_service=vault_service,
    )

    # Initialize command run manager
    command_run_manager = CommandRunManager(
        retention_minutes=60,
        max_events_per_run=200,
    )

    # Initialize service container (replaces per-module init_services calls)
    init_container(
        vault_service=vault_service,
        vault_browser_service=vault_browser_service,
        vault_search_service=vault_search_service,
        git_service=git_service,
        inbox_service=inbox_service,
        agent_service=agent_service,
        log_service=log_service,
        chat_session_manager=chat_session_manager,
        agent_chat_service=agent_chat_service,
        agent_session_manager=agent_session_manager,
        chat_title_service=chat_title_service,
        push_notification_service=push_notification_service,
        relay_client=relay_client,
        claude_session_api=claude_session_api,
        health_service=health_service,
        command_service=command_service,
        command_run_manager=command_run_manager,
        agent_identity_service=agent_identity_service,
        schedule_service=schedule_service,
    )

    if settings.git_enabled:
        logger.info(f"Prime server ready (Git-enabled: {settings.vault_repo_url})")
    else:
        logger.info("Prime server ready (local-only mode)")

    # Start schedule loop
    schedule_service.start()

    # Start background git pull task
    git_pull_task = asyncio.create_task(periodic_git_pull(git_service))

    yield

    # Cleanup: Cancel background task and terminate sessions
    logger.info("Prime server shutting down")

    # Stop agent sessions
    logger.info("Shutting down agent sessions")
    await agent_session_manager.stop_cleanup_loop()
    await agent_session_manager.terminate_all_sessions()

    # Stop git pull task
    git_pull_task.cancel()
    try:
        await git_pull_task
    except asyncio.CancelledError:
        pass

    # Stop schedule loop
    await schedule_service.stop()


app = FastAPI(
    title="Prime Server",
    description="Brain dump capture API",
    version="0.1.0",
    lifespan=lifespan,
)

# Add request ID middleware (must be after FastAPI creation, before CORS middleware)
app.add_middleware(RequestIDMiddleware)

# Configure CORS for SSE streaming from client apps
if settings.cors_enabled:
    # Validate CORS configuration
    allowed_origins = settings.cors_allowed_origins
    if settings.environment == "production":
        for origin in allowed_origins:
            if not origin.startswith("https://"):
                msg = f"CORS origin must be HTTPS in production: {origin}"
                raise ValueError(msg)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=settings.cors_allowed_methods,
        allow_headers=settings.cors_allowed_headers,
        max_age=3600,  # Cache preflight for 1 hour
    )
    logger.info(f"CORS configured for origins: {allowed_origins}")
else:
    logger.warning("CORS is disabled - cross-origin requests will be blocked")

app.include_router(capture.router, tags=["capture"])
app.include_router(chat.router)
app.include_router(claude_sessions.router)
app.include_router(commands.router, tags=["commands"])
app.include_router(config.router)
app.include_router(files.router, tags=["files"])
app.include_router(git.router, tags=["git"])
app.include_router(health.router)
app.include_router(monitoring.router, tags=["monitoring"])
app.include_router(schedule.router, tags=["schedule"])
app.include_router(push.router, tags=["push"])
app.include_router(vault_browser.router, tags=["vault"])
app.include_router(vault_search.router, tags=["vault"])
