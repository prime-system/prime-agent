import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Set up minimal test environment BEFORE any imports from app
# This must happen before pytest collects tests
_tmp_dir = tempfile.TemporaryDirectory(prefix="pytest_config_")
_config_file = Path(_tmp_dir.name) / "config.yaml"
_config_file.write_text(
    """
vault:
  path: /tmp/test-vault

auth:
  token: test-token-123

anthropic:
  api_key: sk-ant-test
  model: claude-3-5-sonnet-20241022
"""
)
os.environ["CONFIG_PATH"] = str(_config_file)


@pytest.fixture(autouse=True)
async def reset_vault_lock_after_test():
    """Reset vault lock after each test to prevent state leakage.

    This fixture ensures each test starts with a clean lock state.
    Without this, tests could interfere with each other.
    """
    yield
    from app.services.lock import reset_lock_for_testing
    await reset_lock_for_testing()


@pytest.fixture(scope="session", autouse=True)
def setup_test_env(tmp_path_factory):
    """Set up test environment variables before importing app modules."""
    os.environ.setdefault("VAULT_REPO_URL", "git@github.com:test/vault.git")
    os.environ.setdefault("AUTH_TOKEN", "test-token-123")
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-api-key-123")
    os.environ.setdefault("AGENT_MODEL", "claude-3-5-sonnet-20241022")
    os.environ.setdefault("VAULT_PATH", "/tmp/test-vault")

    # Create a minimal test config file for ConfigManager initialization
    tmp_path = tmp_path_factory.mktemp("config")
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
vault:
  path: /tmp/test-vault

auth:
  token: test-token-123

anthropic:
  api_key: sk-ant-test
  model: claude-3-5-sonnet-20241022
"""
    )
    os.environ.setdefault("CONFIG_PATH", str(config_file))


@pytest.fixture
def temp_vault():
    """Create a temporary vault directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vault_path = Path(tmpdir) / "vault"
        vault_path.mkdir()
        yield vault_path


@pytest.fixture
def mock_git_service():
    """Mock GitService for testing without actual git operations."""
    mock = MagicMock()
    mock.pull = MagicMock()
    mock.commit_and_push = MagicMock()
    mock.initialize = MagicMock()
    return mock


@pytest.fixture
def test_app():
    """Create a test FastAPI app without the lifespan that initializes git."""
    from app.api import capture, health

    app = FastAPI(title="Prime Server Test")
    app.include_router(capture.router, tags=["capture"])
    app.include_router(health.router)

    return app


@pytest.fixture
def client(temp_vault, mock_git_service, test_app):
    """Test client with mocked services."""
    from app.services.inbox import InboxService
    from app.services.vault import VaultService
    from app.services.container import init_container
    from app.services.chat_session_manager import ChatSessionManager
    from app.services.agent_chat import AgentChatService
    from app.services.agent_session_manager import AgentSessionManager
    from app.services.logs import LogService
    from app.services.claude_session_api import ClaudeSessionAPI
    from app.services.health import HealthCheckService
    from app.config import settings

    vault_service = VaultService(str(temp_vault))
    vault_service.ensure_structure()
    inbox_service = InboxService()
    log_service = LogService(logs_dir=vault_service.logs_path(), vault_path=vault_service.vault_path)
    chat_session_manager = ChatSessionManager(
        vault_path=str(temp_vault),
        claude_home="/tmp/test-claude",
    )
    agent_chat_service = MagicMock(spec=AgentChatService)
    agent_session_manager = MagicMock(spec=AgentSessionManager)
    claude_session_api = MagicMock(spec=ClaudeSessionAPI)
    health_service = HealthCheckService(
        vault_service=vault_service,
        git_service=mock_git_service,
        apn_service=None,
        version="test-version",
    )

    # Initialize container with mocked services
    init_container(
        vault_service=vault_service,
        git_service=mock_git_service,
        inbox_service=inbox_service,
        agent_service=MagicMock(),
        log_service=log_service,
        chat_session_manager=chat_session_manager,
        agent_chat_service=agent_chat_service,
        agent_session_manager=agent_session_manager,
        apn_service=None,
        claude_session_api=claude_session_api,
        health_service=health_service,
    )

    with TestClient(test_app) as c:
        yield c


@pytest.fixture
def auth_headers():
    """Valid authorization headers."""
    return {"Authorization": "Bearer test-token-123"}


@pytest.fixture
def sample_capture_request():
    """Sample capture request payload."""
    return {
        "text": "This is a test thought",
        "source": "iphone",
        "input": "voice",
        "captured_at": "2025-12-21T14:30:00Z",
        "context": {"app": "shortcuts"},
    }
