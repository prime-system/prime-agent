# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Prime Agent is a FastAPI server that captures brain dumps, processes them using Claude Agent SDK, and organizes them into a structured knowledge vault. The system supports Git synchronization, Apple Push Notifications, and configurable inbox organization.

## Development Commands

### First-Time Setup

Before running the server, you need to configure environment variables:

1. **Create `.env` file from template:**
   ```bash
   cp .env.example .env
   ```

2. **Edit `.env` with your credentials:**
   ```bash
   # Required variables (minimum to run)
   ANTHROPIC_API_KEY=sk-ant-your-actual-api-key-here
   AUTH_TOKEN=your-secure-random-token-here

   # Generate a secure token with:
   openssl rand -base64 32
   ```

3. **Optional: Configure Git or APNs** (if needed)
   - For Git sync: Set `GIT_SSH_KEY` or `GIT_USERNAME`/`GIT_TOKEN`
   - For push notifications: Set Apple credentials (`APPLE_TEAM_ID`, etc.)
   - See `.env.example` for all available options

The `.env` file is automatically loaded by docker-compose and **never committed** (protected by `.gitignore`).

### Quick Start with Make

The project includes a Makefile for common development tasks:

```bash
# Show all available commands
make help

# Docker development (recommended)
make dev              # Start server with docker compose
make dev-build        # Rebuild and start server
make dev-down         # Stop server
make dev-logs         # Follow container logs
make dev-shell        # Open bash shell in container

# Local development
make install-dev      # Install Python dev dependencies
make lint             # Run ruff linter
make lint-fix         # Auto-fix linting issues
make format           # Format code with ruff
make type-check       # Run mypy type checker
make test             # Run pytest tests
make check            # Run all checks (lint + type-check + test)
make clean            # Remove cache files
```

### Docker Compose Setup

The `docker-compose.yml` provides a complete development environment:

**Volumes:**
- `vault:/vault` - Knowledge vault storage (persistent)
- `primeai-claude:/home/prime/.claude` - Claude sessions (persistent)
- `primeai-data:/data` - APNs device tokens and other data (persistent)
- `./config.default.yaml:/app/config.yaml:ro` - Configuration (read-only mount)

**Required Environment Variables:**
- `ANTHROPIC_API_KEY` - Claude API key (required)
- `AUTH_TOKEN` - API authentication token (required)

**Optional Environment Variables:**
- `ENVIRONMENT` - Deployment environment ("development" or "production", defaults to development)
- `ANTHROPIC_BASE_URL` - Custom Anthropic API endpoint
- `GIT_SSH_KEY` - SSH private key for git (if git enabled)
- `GIT_USERNAME` - Git username for HTTPS (if git enabled)
- `GIT_TOKEN` - Git token/password for HTTPS (if git enabled)

Note: CORS configuration is **automatic** via `base_url` setting in config.yaml. No additional environment variables needed!

**Example .env file:**
```bash
ANTHROPIC_API_KEY=sk-ant-...
AUTH_TOKEN=your-secure-token
# Optional git configuration
GIT_SSH_KEY=-----BEGIN OPENSSH PRIVATE KEY-----...
```

### Manual Setup (without Docker)

```bash
# Install dependencies (requires Python 3.11+)
pip install -r requirements.txt

# Install with development dependencies
pip install -e ".[dev]"

# Run with uvicorn (development)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Code Quality

All code quality commands work with the Makefile:

```bash
# Using Makefile (recommended)
make lint             # Run ruff linter
make lint-fix         # Auto-fix linting issues
make format           # Format code with ruff
make type-check       # Run mypy type checker
make check            # Run all checks

# Direct commands (if not using Make)
ruff check app tests
ruff check --fix app tests
ruff format app tests
mypy app tests
```

### Testing

```bash
# Using Makefile
make test             # Run all tests

# Direct pytest commands
pytest                                    # Run all tests
pytest --cov=app --cov-report=html       # With coverage
pytest tests/test_vault.py -v            # Specific test file
pytest tests/test_vault.py::test_name -v # Single test
```

### Docker Volume Management

Persistent data is stored in named Docker volumes:

```bash
# List volumes
docker volume ls | grep primeai

# Inspect volume contents
docker run --rm -v primeai_vault:/vault alpine ls -la /vault

# Backup vault data
docker run --rm -v primeai_vault:/vault -v $(pwd):/backup alpine \
  tar czf /backup/vault-backup.tar.gz -C /vault .

# Restore vault data
docker run --rm -v primeai_vault:/vault -v $(pwd):/backup alpine \
  tar xzf /backup/vault-backup.tar.gz -C /vault

# Remove all volumes (WARNING: deletes all data)
make dev-down
docker volume rm primeai_vault primeai_claude primeai_data
```

## Architecture

### Core Services Pattern

The application uses a **dependency injection pattern** where services are initialized at startup in `app/main.py:lifespan()` and injected into API route modules via `init_services()` functions. This avoids circular imports and enables clean service composition.

**Service Lifecycle:**
1. Services instantiated in `lifespan()` (app/main.py:71-179)
2. Injected into API modules via `init_services()` (e.g., app/api/capture.py:21-31)
3. Services remain singletons throughout application lifetime

**Key Services:**
- `VaultService` - Manages vault directory structure and path resolution
- `GitService` - Handles git operations (pull, commit, push)
- `InboxService` - Formats and writes capture files
- `AgentService` - Invokes Claude Agent SDK for dump processing
- `AgentWorker` - Orchestrates background processing with locking
- `APNService` - Sends push notifications to iOS/macOS clients

### Configuration System

**Two-Level Configuration:**

1. **Server Config** (`config.yaml`) - Environment and API settings
   - Location: `/app/config.yaml` (or `CONFIG_PATH` env var)
   - Supports `${ENV_VAR}` expansion (app/config.py:10-31)
   - Dynamically reloaded on file changes via `ConfigManager` (app/config.py:251-287)
   - Required: `ANTHROPIC_API_KEY`, `AUTH_TOKEN`

2. **Vault Config** (`.prime/settings.yaml` in vault root) - Capture organization
   - Controls inbox folder name, file patterns, weekly subfolders
   - Loaded lazily with change detection (app/services/vault.py:19-46)
   - See VAULT_CONFIG.md for full documentation

**CORS Configuration** - Automatically derived from `base_url`:
   - Set `base_url` in `config.yaml` (e.g., `https://app.example.com`)
   - CORS origins auto-derived based on environment (development vs production)
   - Development: base_url + localhost alternatives (http://localhost:3000, etc.)
   - Production: base_url only + HTTPS enforced at startup
   - HTTP methods: Limited to POST, GET, OPTIONS (no manual config needed)
   - Headers: Limited to Authorization, Content-Type (no manual config needed)
   - Security: Prevents CSRF attacks via explicit origin allowlist

**Example config.yaml (Development):**
```yaml
environment: development
base_url: http://localhost:8000
```

**Example config.yaml (Production):**
```yaml
environment: production
base_url: https://app.example.com
# CORS origins auto-derived to: ["https://app.example.com"]
# HTTPS enforced - startup fails if HTTP base_url in production
```

### Data Flow: Capture → Process → Organize

**Capture Flow** (app/api/capture.py):
1. POST `/capture` receives raw thought from client
2. Generate title with Claude Haiku if `{title}` in file pattern
3. Write to inbox file with YAML frontmatter
4. Queue git commit in background (non-blocking)
5. Return immediately to client

**Processing Flow** (app/services/worker.py):
1. POST `/api/processing/trigger` fires AgentWorker
2. Worker acquires `vault_lock` (prevents concurrent processing)
3. Pulls latest changes from git (if enabled)
4. Invokes Claude Agent SDK with `/processCapture` prompt
5. Agent reads unprocessed captures, organizes into vault structure
6. Creates audit log in `.prime/logs/`
7. Commits all changes to git
8. Releases lock

**Key Insight:** Capture and processing are decoupled. Captures return instantly, processing happens on-demand via separate endpoint.

### Agent SDK Integration

The system uses **Claude Agent SDK** (`claude_agent_sdk`) for autonomous processing:

**Configuration** (app/services/agent.py:128-138):
- Runs in project directory (`cwd=vault_path`)
- Loads `.claude/commands/` from vault (custom prompts)
- Uses `permission_mode="acceptEdits"` (auto-approve file ops)
- Budget-limited processing (`max_budget_usd`)

**Processing Prompt:**
- Custom command: `.claude/commands/processCapture.md` in vault (if exists)
- Fallback: `app/prompts/processCapture.md` from source
- Agent autonomously transforms inbox dumps into structured knowledge

### Vault Structure

```
/vault/
├── .prime/
│   ├── settings.yaml        # Vault configuration (optional)
│   ├── inbox/              # Default inbox location (configurable)
│   │   └── 2026-W01/       # Weekly subfolders (optional)
│   └── logs/               # Processing audit logs
├── .claude/
│   └── commands/           # Custom agent prompts (optional)
│       └── processCapture.md
├── Daily/                  # Daily notes (created by agent)
├── Notes/                  # Permanent notes (created by agent)
├── Projects/               # Project folders (created by agent)
├── Tasks/                  # Task management (created by agent)
└── Questions/              # Open questions (created by agent)
```

**Note:** Only `.prime/` directory is created at startup. All other folders (Daily, Notes, etc.) are created on-demand by the Claude Agent during processing.

### Locking and Concurrency

**Global Lock** (`vault_lock` in app/services/lock.py):
- Protects vault filesystem from concurrent writes
- Shared between capture endpoint and agent worker
- Ensures git operations are serialized

**Worker Singleton** (`AgentWorker._processing` flag):
- Prevents multiple processing runs
- Fire-and-forget trigger pattern
- Automatically cleared even on exceptions

### Background Task Error Tracking

**Problem:** Background tasks (like git auto-commit after capture) can fail silently:
- Git auth failure → Commit never happens → Vault out of sync
- Network error → Push fails → No backup of capture
- Users receive `200 OK` response even if commit failed → Data loss scenario

**Solution:** All background tasks must use `safe_background_task()` wrapper:

```python
from app.services.background_tasks import safe_background_task

# BEFORE (dangerous - errors silently ignored)
background_tasks.add_task(git_service.auto_commit_and_push)

# AFTER (safe - errors logged and tracked)
background_tasks.add_task(
    safe_background_task,
    "git_auto_commit",  # Task name for logging
    git_service.auto_commit_and_push  # Callable to execute
)
```

**Monitoring Task Status:**
```bash
# Check background task health (requires AUTH_TOKEN)
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/monitoring/background-tasks/status

# Response:
{
    "successful_tasks": 42,
    "failed_tasks": 2,
    "recent_failures": [
        {
            "task": "git_auto_commit",
            "error": "Push failed: authentication error",
            "type": "GitError",
            "timestamp": "2026-01-02T14:30:45.123456"
        }
    ]
}
```

**Implementation Details:**
- `BackgroundTaskTracker` maintains history of successes/failures
- All exceptions are logged with full context (traceback included)
- Failed tasks are accessible via monitoring endpoint for alerting
- Last 5 failures always available (configurable history size)
- Thread-safe for concurrent task execution

### Git Integration

**Three Git Operations:**

1. **Auto-commit** (background, after capture):
   - Best-effort, errors ignored
   - Commits individual captures
   - Non-blocking (app/api/capture.py:86)

2. **Periodic pull** (every 5 minutes):
   - Background task in `lifespan()` (app/main.py:42-68)
   - Syncs remote changes to vault
   - Continues on errors

3. **Processing commit** (after agent run):
   - Commits all vault changes atomically
   - Includes processing log
   - Critical operation, logged on failure

**Git Authentication:**
- SSH: Requires `GIT_SSH_KEY` env var (private key)
- HTTPS: Requires `GIT_USERNAME` and `GIT_TOKEN` env vars

### CORS Security (Prevents CSRF Attacks)

**Vulnerability Fixed:** CWE-352 (Cross-Site Request Forgery)

The application enforces strict CORS (Cross-Origin Resource Sharing) policies to prevent malicious websites from injecting captures into user vaults. CORS origins are **automatically derived from `base_url`** - users don't need to manually configure domains.

**How It Works:**

1. **User sets `base_url` in config.yaml** (e.g., `https://app.example.com`)
2. **CORS origins auto-derived based on environment:**
   - Development: `base_url` + localhost alternatives (http://localhost:3000, http://127.0.0.1:3000, etc.)
   - Production: `base_url` only (HTTPS enforced at startup)
3. **Browser blocks unauthorized origins** before requests reach the server

**Configuration (Development):**
```yaml
environment: development
base_url: http://localhost:8000
# CORS automatically includes:
# - http://localhost:8000
# - http://localhost:3000
# - http://127.0.0.1:3000, http://127.0.0.1:8000
```

**Configuration (Production):**
```yaml
environment: production
base_url: https://app.example.com
# CORS automatically includes:
# - https://app.example.com
# - HTTPS enforced (startup fails with HTTP base_url)
```

**Automatic Restrictions (No Manual Config):**
- HTTP Methods: POST, GET, OPTIONS (no DELETE, PUT, PATCH)
- Headers: Authorization, Content-Type (no custom headers)
- Preflight Cache: 3600 seconds (1 hour - prevents request flooding)

**Security Guarantees:**
- ✅ Explicit origin allowlist (no wildcards)
- ✅ No credentials with wildcard origins
- ✅ HTTPS enforced in production at startup
- ✅ Browser blocks unauthorized origins
- ✅ Tests verify all security scenarios (app/test_cors_security.py)

**Attack Prevention Example:**
```javascript
// attacker.com/malicious.html
fetch('https://primeapp.com/capture', {
    method: 'POST',
    credentials: 'include',  // Would be sent in old vulnerable config
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        text: "Malicious capture injected into vault"
    })
})
// ❌ BLOCKED: Browser sees Origin: attacker.com
// ❌ Response missing Access-Control-Allow-Origin header
// ❌ Request never reaches the server
```

See: `app/config.py:100-130` for `_get_cors_origins_from_base_url()` implementation and `tests/test_cors_security.py` for comprehensive security tests.

## Important Patterns

### Environment Variable Expansion

Config files use `${VAR_NAME}` syntax, expanded at startup:

```yaml
# config.yaml
anthropic:
  api_key: ${ANTHROPIC_API_KEY}  # Expands to env var value
```

Expansion logic in `app/config.py:10-31`. Missing variables raise clear errors.

### YAML Frontmatter in Captures

Every capture is a standalone Markdown file with metadata:

```markdown
---
id: 2026-01-02T14:30:45Z-iphone
captured_at: 2026-01-02T14:30:45Z
source: iphone
input: voice
context:
  app: shortcuts
---

Raw capture text here...
```

Agent marks as processed by adding `processed: true` to frontmatter.

### Dynamic Configuration Reloading

Both server config and vault config reload automatically:
- Server: `_SettingsProxy` checks file mtime on every access (app/config.py:254-287)
- Vault: `vault_config` property checks `.prime/settings.yaml` mtime (app/services/vault.py:19-46)

Changes apply immediately without restart.

**TOCTOU Race Condition Prevention:**

The configuration system prevents Time-of-Check-Time-of-Use (TOCTOU) race conditions where:
1. File mtime is checked
2. File is modified between check and read
3. Inconsistent data is loaded

**Safe Reload Pattern** (app/services/config_manager.py:93-200):

1. **Read file first** (atomic operation):
   ```python
   config_str = self.config_path.read_text()  # Single syscall, atomic
   ```

2. **Check mtime after read** (consistent with contents):
   ```python
   current_mtime = self.config_path.stat().st_mtime
   ```

3. **Skip reload if mtime unchanged**:
   ```python
   if self._last_mtime is not None and current_mtime == self._last_mtime:
       return  # No changes
   ```

4. **Validate before applying**:
   ```python
   new_settings = Settings(**flat_config)  # Parse & validate
   new_settings.validate_git_config()      # Semantic checks
   new_settings.validate_cors_config()
   ```

5. **Atomic config update**:
   ```python
   self._current_settings = new_settings  # Single assignment
   self._last_mtime = current_mtime
   ```

**Benefits:**
- ✅ No race conditions between check and use
- ✅ File contents are always consistent
- ✅ Invalid configs don't corrupt system state
- ✅ Optimization: skip unnecessary reloads
- ✅ Thread-safe with GIL protection
- ✅ Comprehensive error handling

### Strict Type Checking

Project uses `mypy` in strict mode with comprehensive linting. When adding code:
- All functions must have type annotations
- Use `from __future__ import annotations` for forward references
- Pydantic models for data validation
- No `Any` types without justification

Ignored rules (see pyproject.toml:83-101):
- `PLR0913` - Many function arguments (acceptable for service constructors)
- `B008` - Function calls in defaults (FastAPI `Depends()` pattern)
- `ARG001` - Unused arguments (FastAPI route signatures)

### Logging Conventions

All application logging uses **structured JSON format** for better observability.

**Pattern:**

```python
import logging

logger = logging.getLogger(__name__)  # Module-level logger

# ✓ GOOD - Structured fields in extra dict (parsed by log aggregators)
logger.info("Capture received", extra={
    "dump_id": dump_id,
    "source": request.source.value,
})

# ❌ BAD - String formatting (not parsed by log aggregators)
logger.info(f"Capture received: {dump_id}")
```

**Log Levels:**

- `logger.debug()` - Detailed internal state (disabled in production)
- `logger.info()` - Normal operation milestones
- `logger.warning()` - Recoverable issues
- `logger.error()` - Operation failures
- `logger.exception()` - Exceptions with traceback

**JSON Output:**

When configured, logs output as structured JSON:

```json
{
  "timestamp": "2026-01-05T14:30:47.123Z",
  "level": "INFO",
  "name": "app.services.git",
  "message": "Auto-commit and push completed",
  "files_count": 3,
  "duration_seconds": 45.23
}
```

**Common Fields:**

- `error` - Error message (string)
- `error_type` - Exception type name (string)
- `duration_seconds` - Operation duration (float)
- `cost_usd` - API cost (float)
- `files_count` - Number of files (int)
- `dump_id` - Unique capture ID (string)

**Configuration:**

Logging is initialized at startup in `app/main.py:29`:

```python
from app.logging_config import configure_json_logging

configure_json_logging(log_level=settings.log_level)
```

See `LOGGING_STANDARDS.md` for detailed guidelines and examples.

Asyncio warning suppressed for Claude SDK task context issue (app/main.py:36-43).

### Concurrency Model: Pure Asyncio Only

**Critical: NO mixing of threading primitives with async code.**

This codebase uses pure `asyncio` for all concurrency. Threading primitives (`threading.Lock`, `threading.Thread`, etc.) are **strictly forbidden** in async contexts as they can cause deadlocks.

**Why:** In asyncio, only one coroutine runs at a time (single-threaded event loop). A blocking `threading.Lock` holds the GIL while the event loop is blocked, preventing any other coroutine from running.

**Rules:**

1. **Use `asyncio.Lock` not `threading.Lock`:**
   ```python
   # ✅ CORRECT - Async lock
   import asyncio
   lock = asyncio.Lock()
   async with lock:
       await some_async_operation()

   # ❌ WRONG - Blocks entire event loop
   import threading
   lock = threading.Lock()
   with lock:  # This blocks!
       pass
   ```

2. **Initialize `asyncio.Lock` in event loop:**
   ```python
   # Global lock reference
   _lock: asyncio.Lock | None = None

   async def init_lock() -> asyncio.Lock:
       """Initialize in running event loop at startup."""
       global _lock
       _lock = asyncio.Lock()
       return _lock

   def get_lock() -> asyncio.Lock:
       """Get initialized lock."""
       if _lock is None:
           raise RuntimeError("Lock not initialized")
       return _lock
   ```

3. **Offload blocking I/O to executor:**
   ```python
   # ✅ CORRECT - File I/O in executor
   loop = asyncio.get_event_loop()
   result = await loop.run_in_executor(None, blocking_file_operation)

   # ❌ WRONG - Blocks event loop
   result = blocking_file_operation()
   ```

4. **Use `asyncio.TaskGroup` for concurrent tasks (Python 3.11+):**
   ```python
   # ✅ CORRECT - TaskGroup
   async with asyncio.TaskGroup() as tg:
       tg.create_task(task1())
       tg.create_task(task2())
       # Automatically waits and handles exceptions

   # ⚠️ ACCEPTABLE - Manual gather (legacy)
   tasks = [asyncio.create_task(task1()), asyncio.create_task(task2())]
   await asyncio.gather(*tasks)
   ```

5. **Use `asyncio.Queue` not `queue.Queue`:**
   ```python
   # ✅ CORRECT
   queue: asyncio.Queue = asyncio.Queue()
   await queue.put(item)
   item = await queue.get()

   # ❌ WRONG - Not async-safe
   from queue import Queue
   queue = Queue()  # Blocking operations
   ```

**Initialization in `app/main.py:lifespan()`:**

All async locks must be initialized in the running event loop during startup:
```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Initialize ALL async locks here
    await init_vault_lock()
    await push_tokens.init_file_lock()
    # ... more services ...
    yield
    # Cleanup
```

**Examples in Codebase:**

- ✅ `app/services/lock.py` - Global vault lock (asyncio.Lock)
- ✅ `app/services/background_tasks.py` - Task tracker with asyncio.Lock
- ✅ `app/services/agent_session_manager.py` - Session management with asyncio primitives
- ✅ `app/services/push_tokens.py` - File operations with asyncio.Lock
- ✅ `tests/test_concurrency_model.py` - Comprehensive concurrency tests

**Common Mistake Prevention:**

```python
# ❌ NEVER DO THIS
class MyService:
    def __init__(self):
        self.lock = threading.Lock()  # WRONG - blocks event loop!

    async def process(self):
        with self.lock:  # This locks out all other coroutines
            await db.query()

# ✅ DO THIS INSTEAD
class MyService:
    def __init__(self):
        self.lock: asyncio.Lock | None = None

    async def init_lock(self) -> None:
        """Call from lifespan()"""
        self.lock = asyncio.Lock()

    async def process(self):
        async with self.lock:
            await db.query()
```

### Security Best Practices: Credential Handling

**Critical: Never log credentials in any form.** Exposed credentials in Docker logs, CI/CD pipelines, and log aggregation systems pose significant security risks (CWE-532, PCI-DSS violation).

**What NEVER to log:**
- API keys or tokens (e.g., `ANTHROPIC_API_KEY`, `AUTH_TOKEN`)
- Credential identifiers (team IDs, key IDs) - even metadata can reveal infrastructure
- Partial credentials (first 50 chars of keys)
- Credential lengths (hints at key size)
- PEM-formatted private keys (SSH keys, p8 keys)
- Database passwords or connection strings

**What IS safe to log:**
- Non-secret identifiers: bundle IDs (`com.example.app`), usernames, email addresses
- Operation status: "APNs service initialized successfully"
- Path information: directory locations, file paths
- Non-credential configuration: feature flags, environment names

**Examples:**

❌ BAD:
```python
logger.info(f"APNs credentials - team_id: {settings.apple_team_id}, key_id: {settings.apple_key_id}")
print(f"API key: {api_key[:50]}...")  # Partial key exposed!
logger.error(f"Git auth failed: {GIT_SSH_KEY}")  # Full key in error log!
```

✅ GOOD:
```python
logger.debug("APNs service configured: bundle_id=%s", settings.apple_bundle_id)
logger.info("APNs service initialized successfully")  # No details needed
logger.error("Git authentication failed (credentials invalid)")  # Generic message
```

**Redaction Utility:**
The `app/utils/redaction.py` module provides utilities to safely redact credentials:

```python
from app.utils.redaction import redact_dict, redact_sensitive_data

# Redact dictionary keys by pattern
config = {"api_key": "sk-ant-...", "bundle_id": "com.example.app"}
safe_config = redact_dict(config)
# Result: {"api_key": "[REDACTED]", "bundle_id": "com.example.app"}

# Redact text strings by regex pattern
text = "Key: sk-ant-abc123def456"
safe_text = redact_sensitive_data(text)
# Result: "Key: [REDACTED_api_key]"
```

**Pre-commit Verification:**
Before committing code, verify no credentials are logged:

```bash
# Search for dangerous logging patterns
grep -r "api_key\|auth_token\|p8_key\|password\|secret" app/ --include="*.py" | grep -E "print|logger"

# Should return EMPTY if safe. Non-empty results need fixing.
```

## Common Development Tasks

### Adding a New API Endpoint

1. Create/modify route in `app/api/` directory
2. Add service dependencies via `init_services()` pattern
3. Use `Depends(verify_token)` for authentication
4. Return Pydantic models for response validation

Example:
```python
from fastapi import APIRouter, Depends
from app.dependencies import verify_token

router = APIRouter()

@router.get("/my-endpoint")
async def my_endpoint(_: None = Depends(verify_token)) -> dict:
    return {"status": "ok"}
```

### Modifying Agent Behavior

**Option 1: Vault-specific prompt** (recommended):
1. Create `.claude/commands/processCapture.md` in vault
2. Add YAML frontmatter with command metadata
3. Agent automatically uses vault version

**Option 2: Default prompt** (affects all vaults):
1. Edit `app/prompts/processCapture.md`
2. Changes apply to vaults without custom command

### Adding Vault Configuration Options

1. Add fields to `VaultConfig` model (app/models/vault_config.py)
2. Update default config in `load_vault_config()`
3. Use in `VaultService` via `self.vault_config.your_field`
4. Document in VAULT_CONFIG.md

### Working with Git Operations

Always use `GitService` methods, never call git directly:

```python
# Pull latest changes
git_service.pull()

# Check for changes
changed_files = git_service.get_changed_files()

# Commit and push
git_service.commit_and_push("Your message", changed_files)
```

Git operations raise `GitError` on failures. Wrap in try-except and log appropriately.

### Docker Development Workflow

**Starting Development:**
```bash
# First time setup
make dev-build    # Build image and start container

# Subsequent runs
make dev          # Start with existing image
```

**Making Code Changes:**
1. Edit code locally (files sync via volume mount)
2. For Python code changes: container auto-reloads (uvicorn --reload)
3. For dependency changes: run `make dev-build` to rebuild

**Debugging:**
```bash
# View logs
make dev-logs

# Open shell in running container
make dev-shell

# Inside container:
ps aux              # Check processes
ls -la /vault       # Inspect vault
cat /app/config.yaml # View config
python -c "from app.config import settings; print(settings.vault_path)"
```

**Testing in Docker:**
```bash
# Run tests inside container
make dev-shell
pytest

# Or run directly
docker compose exec primeai pytest
```

**Resetting Environment:**
```bash
make dev-down     # Stop container
make clean        # Remove Python cache files

# Remove volumes (WARNING: deletes all data)
docker volume rm primeai_vault primeai_claude primeai_data
```

**Troubleshooting:**

*Problem: "Environment variable 'X' referenced in config.yaml but not set"*
```bash
# Solution: Check your .env file exists and has all required variables
cat .env

# Verify docker-compose loads it
docker compose config | grep -A5 environment

# If .env is missing, create from template
cp .env.example .env
# Then edit with your actual values
```

*Problem: Container exits immediately*
```bash
# Check logs for the error
docker compose logs primeai

# Most common issues:
# 1. Missing ANTHROPIC_API_KEY or AUTH_TOKEN in .env
# 2. Invalid YAML in config.default.yaml
# 3. Missing Python dependencies (run make dev-build)
```

*Problem: Changes not reflected in container*
```bash
# Python code changes: auto-reload should work
# If not, restart container
make dev-down && make dev

# Dependency changes: rebuild required
make dev-build

# Config changes: restart container
docker compose restart primeai
```

## Key Files Reference

**Application Core:**
- `app/main.py` - Application entry point, service initialization
- `app/config.py` - Configuration loading with env var expansion
- `app/services/agent.py` - Claude Agent SDK integration
- `app/services/worker.py` - Background processing orchestration
- `app/services/vault.py` - Vault path management and structure
- `app/services/git.py` - Git operations wrapper
- `app/api/capture.py` - Capture endpoint (write to inbox)
- `app/api/processing.py` - Processing trigger endpoint
- `app/models/vault_config.py` - Vault configuration schema

**Configuration & Infrastructure:**
- `config.default.yaml` - Default server configuration template
- `.env.example` - Environment variable template (copy to `.env`)
- `.env` - Local environment variables (ignored by git)
- `docker-compose.yml` - Docker development environment with volumes
- `Dockerfile` - Container image definition
- `Makefile` - Development task automation
- `.gitignore` - Git ignore patterns (protects secrets)
- `pyproject.toml` - Python dependencies and tool configuration
- `requirements.txt` - Production dependencies

**Documentation:**
- `CLAUDE.md` - This file (development guide)
- `VAULT_CONFIG.md` - Complete vault configuration documentation
