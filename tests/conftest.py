import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """Set up test environment variables before importing app modules."""
    os.environ.setdefault("VAULT_REPO_URL", "git@github.com:test/vault.git")
    os.environ.setdefault("AUTH_TOKEN", "test-token-123")
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-api-key-123")
    os.environ.setdefault("AGENT_MODEL", "claude-3-5-sonnet-20241022")
    os.environ.setdefault("VAULT_PATH", "/tmp/test-vault")


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
    from app.api import capture

    app = FastAPI(title="Prime Server Test")
    app.include_router(capture.router, tags=["capture"])

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


@pytest.fixture
def client(temp_vault, mock_git_service, test_app):
    """Test client with mocked services."""
    from app.api import capture
    from app.services.inbox import InboxService
    from app.services.vault import VaultService

    vault_service = VaultService(str(temp_vault))
    vault_service.ensure_structure()
    inbox_service = InboxService()

    capture.init_services(vault_service, mock_git_service, inbox_service)

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
