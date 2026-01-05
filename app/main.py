import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import capture, chat, claude_sessions, config, files, git, processing, push
from app.config import settings
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
from app.services.worker import AgentWorker

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Suppress known asyncio warning from Claude SDK task context issue
# The SDK creates cancel scopes in one task but they're exited in another
# This is a known SDK issue and doesn't affect functionality
asyncio_logger = logging.getLogger("asyncio")
class AsyncioErrorFilter(logging.Filter):
    def filter(self, record):
        # Suppress: "Attempted to exit cancel scope in a different task"
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

    # Initialize services
    vault_service = VaultService(settings.vault_path)

    git_service = GitService(
        vault_path=settings.vault_path,
        enabled=settings.git_enabled,
        repo_url=settings.vault_repo_url,
        user_name=settings.git_user_name,
        user_email=settings.git_user_email,
    )

    inbox_service = InboxService()

    # Initialize agent services
    agent_service = AgentService(
        vault_path=settings.vault_path,
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_base_url,
        max_budget_usd=settings.agent_max_budget_usd,
    )

    log_service = LogService(logs_dir=vault_service.logs_path(), vault_path=vault_service.vault_path)

    # Initialize chat session manager (works directly with Claude sessions)
    chat_session_manager = ChatSessionManager(
        vault_path=settings.vault_path,
        claude_home="/home/prime/.claude",
    )

    # Initialize agent chat service
    agent_chat_service = AgentChatService(
        vault_path=settings.vault_path,
        api_key=settings.anthropic_api_key,
        model=settings.agent_model,
        base_url=settings.anthropic_base_url,
        git_service=git_service,
    )

    # Initialize git repo (no-op if disabled) and vault structure
    git_service.initialize()
    vault_service.ensure_structure()

    # Initialize APNs service (optional)
    apn_service = None
    if settings.apn_enabled:
        try:
            # Ensure APNs data directory exists
            settings.apn_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"APNs directory initialized: {settings.apn_dir}")
            logger.info(f"APNs devices file: {settings.apn_devices_file}")

            # Initialize APNService
            logger.debug("APNs service configuration loaded (credentials not logged for security)")

            apn_service = APNService(
                devices_file=settings.apn_devices_file,
                key_content=settings.apple_p8_key,  # type: ignore[arg-type]
                team_id=settings.apple_team_id,  # type: ignore[arg-type]
                key_id=settings.apple_key_id,  # type: ignore[arg-type]
                bundle_id=settings.apple_bundle_id,  # type: ignore[arg-type]
                environment="production",  # Default to production
            )
            logger.info("APNs service initialized successfully")
        except ValueError as e:
            logger.error(f"Failed to initialize APNs service: {e}")
            # Continue without APNs if initialization fails
            apn_service = None
    else:
        logger.info("APNs disabled in configuration")

    # Inject services into capture module
    capture.init_services(vault_service, git_service, inbox_service)

    # Inject services into processing module
    processing.init_services(vault_service, inbox_service, log_service)

    # Inject services into config module
    config.init_services(vault_service, settings)

    # Inject services into push module
    push.init_services(apn_service)

    # Initialize AgentSessionManager
    agent_session_manager = AgentSessionManager(agent_service=agent_chat_service)
    agent_session_manager.start_cleanup_loop()

    # Inject services into chat module
    chat.init_services(chat_session_manager, agent_chat_service, agent_session_manager)

    # Inject services into files module
    files.init_service(vault_service)

    # Inject services into git module
    git.init_service(git_service)

    # Initialize Claude session API
    claude_session_api = ClaudeSessionAPI(
        project_path=settings.vault_path,
        claude_home="/home/prime/.claude",
    )
    claude_sessions.init_service(claude_session_api)

    # Initialize agent worker
    AgentWorker.initialize(agent_service, git_service, log_service)

    if settings.git_enabled:
        logger.info(f"Prime server ready (Git-enabled: {settings.vault_repo_url})")
    else:
        logger.info("Prime server ready (local-only mode)")

    logger.info("Agent worker initialized and ready")

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


app = FastAPI(
    title="Prime Server",
    description="Brain dump capture API",
    version="0.1.0",
    lifespan=lifespan,
)

# Configure CORS for SSE streaming from client apps
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins (can be restricted in production)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(capture.router, tags=["capture"])
app.include_router(chat.router)
app.include_router(claude_sessions.router)
app.include_router(config.router)
app.include_router(files.router, tags=["files"])
app.include_router(git.router, tags=["git"])
app.include_router(processing.router)
app.include_router(push.router, prefix="/api/v1", tags=["push"])


@app.get("/health")
async def health() -> dict[str, Any]:
    """Health check endpoint."""
    return {"status": "ok", "git_enabled": settings.git_enabled}
