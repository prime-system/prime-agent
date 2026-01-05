# PrimeAgent

**The intelligent processing engine for Prime.**

A FastAPI server that receives raw brain dumps and transforms them into structured Markdown notes using the Claude Agent SDK. The processing layer that turns chaotic thoughts into clear knowledge.

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Alpha-orange.svg)]()
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)]()

---

## What is PrimeAgent?

PrimeAgent is the **server component** of the Prime personal knowledge system. It provides:

- **HTTP API** for capturing raw, unstructured thoughts
- **Intelligent Processing** using Claude Agent SDK to restructure content
- **Asynchronous Agent** that splits ideas, creates links, extracts tasks
- **Git Sync** to version-control your knowledge vault
- **Serialized Processing** ensuring deterministic, repeatable results

**Part of the Prime Ecosystem:**
- **PrimeAgent** (this repo) - Server and processing engine
- **Prime-App** (private) - iOS/macOS/iPadOS capture app

---

## Why PrimeAgent?

Traditional note-taking requires organization at capture time. PrimeAgent separates capture from thinking:

1. **Capture is dumb** - Accept raw, unstructured input via API
2. **Processing is intelligent** - Claude Agent SDK makes all structural decisions
3. **Knowledge is durable** - Output is plain Markdown, version-controlled, tool-agnostic

> *"I think freely now. Clarity appears later."*

---

## Features

- **RESTful API** - Simple HTTP endpoints for capture and status
- **Individual Capture Files** - Each dump stored separately with YAML frontmatter
- **Claude Agent SDK** - Intelligent, opinionated async processing
- **Markdown Output** - Zettelkasten-style notes with wiki-style links
- **Git Integration** - Automatic commit and push after processing
- **Task Extraction** - Automatic identification of actionable items
- **Question Extraction** - Capture open questions for later review
- **Project Tracking** - Group related ideas into project-centric notes
- **Daily Synthesis** - Aggregate insights into daily notes
- **Push Notifications** - APNs support for processing status updates
- **Budget Control** - Configurable Claude API spending limits
- **Configurable Inbox** - Customize folder structure, filenames, and organization

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Anthropic API key ([get one here](https://console.anthropic.com))
- Optional: Git repository for your vault

### Installation

**1. Clone and configure**

```bash
git clone https://github.com/prime-system/prime-agent.git
cd prime-agent

# Create environment file from template
cp .env.example .env
```

**2. Edit `.env` with your credentials**

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-your-actual-api-key
AUTH_TOKEN=$(openssl rand -base64 32)

# Optional (Git sync)
GIT_SSH_KEY=
GIT_USERNAME=
GIT_TOKEN=
```

**3. Start the server**

```bash
make dev-build
# or
docker compose up --build
```

PrimeAgent runs at `http://localhost:8000`

---

## Your First Capture

### Capture a Thought

```bash
curl -X POST http://localhost:8000/capture \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Had an interesting idea about refactoring the auth system. Should move to JWT with refresh tokens. Also need to research rate limiting approaches for the API.",
    "source": "mac",
    "input": "text",
    "captured_at": "'$(date -u +"%Y-%m-%dT%H:%M:%SZ")'",
    "context": {
      "app": "cli"
    }
  }'
```

**Response:**
```json
{
  "ok": true,
  "inbox_file": "Inbox/2026-01-04_21-30-45_mac.md",
  "dump_id": "2026-01-04T21:30:45Z-mac"
}
```

### Trigger Processing

Processing is manual - trigger it when ready:

```bash
curl -X POST http://localhost:8000/api/processing/trigger \
  -H "Authorization: Bearer $AUTH_TOKEN"
```

### Check Processing Status

```bash
curl http://localhost:8000/api/processing/status \
  -H "Authorization: Bearer $AUTH_TOKEN"
```

**Response:**
```json
{
  "is_running": false,
  "last_run": {
    "timestamp": "2026-01-04T21:32:15Z",
    "duration_seconds": 45.2,
    "cost_usd": 0.0234,
    "success": true
  },
  "unprocessed_count": 0
}
```

### What Happens During Processing

The agent automatically:

1. **Reads Unprocessed Captures** - Scans inbox for files without `processed: true`
2. **Splits Ideas** - Separates distinct concepts (auth refactoring vs. rate limiting)
3. **Creates Notes** - Generates structured Markdown files in vault
4. **Extracts Tasks** - Identifies actionable items
5. **Links Concepts** - Creates wiki-style links between related notes
6. **Marks Complete** - Updates captures with `processed: true` in frontmatter
7. **Commits to Git** - Version-controls all changes (if enabled)

### View the Results

Check your vault:

```
vault/
├── .prime/
│   ├── inbox/
│   │   └── 2026-W01/
│   │       └── 2026-01-04_21-30-45_mac.md    # Original capture
│   └── logs/
│       └── 2026-01-04_21-32-15_process.md    # Processing log
├── Daily/
│   └── 2026-01-04.md                          # Daily synthesis
├── Notes/
│   ├── Authentication System.md               # Structured note
│   └── API Rate Limiting.md                   # Research topic
├── Projects/
│   └── Auth Refactoring.md                    # Project overview
└── Tasks/
    └── Inbox.md                                # Extracted tasks
```

---

## Architecture

### Three Layers

1. **Capture Layer** - FastAPI HTTP endpoints (instant response, fire-and-forget)
2. **Processing Layer** - Claude Agent SDK (intelligent, asynchronous, serialized)
3. **Knowledge Layer** - Markdown files (Zettelkasten, Git-synced, Obsidian-compatible)

### Processing Flow

```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐
│  POST       │────▶│ Write Inbox  │────▶│ Return         │
│  /capture   │     │  File        │     │  Immediately   │
└─────────────┘     └──────────────┘     └────────────────┘

                    (Manual Trigger)

┌─────────────┐     ┌──────────────┐     ┌────────────────┐
│  POST       │────▶│ Start Agent  │────▶│ Process All    │
│  /trigger   │     │  Worker      │     │  Unprocessed   │
└─────────────┘     └──────────────┘     └────────────────┘
                                                   │
                                                   ▼
┌─────────────┐     ┌──────────────┐     ┌────────────────┐
│  Git Push   │◀────│  Commit      │◀────│ Update Vault   │
│  (optional) │     │  Changes     │     │ (Claude SDK)   │
└─────────────┘     └──────────────┘     └────────────────┘
                                                   │
                                                   ▼
                                          ┌────────────────┐
                                          │ Mark Processed │
                                          │ Create Log     │
                                          └────────────────┘
```

### Serialized Processing

**Critical Design Decision:** Processing is strictly serialized (one at a time).

Why:
- Ensures deterministic results
- Prevents Git conflicts
- Maintains context across runs
- Allows agent to read/modify entire vault safely

This is intentional, not a limitation.

---

## Configuration

PrimeAgent uses **YAML configuration** with **environment variables for secrets**.

### Configuration File

The server uses `config.default.yaml` which references environment variables:

```yaml
# config.default.yaml (already in repo)
vault:
  path: /vault

anthropic:
  api_key: ${ANTHROPIC_API_KEY}
  model: "claude-3-5-haiku-latest"
  max_budget_usd: 2.0

auth:
  token: ${AUTH_TOKEN}

git:
  enabled: false  # Enable in your config
  repo_url: null
  user_name: "Prime Agent"
  user_email: "prime@local"

logging:
  level: "INFO"
```

### Environment Variables

Create a `.env` file (from `.env.example`):

**Required:**
```bash
ANTHROPIC_API_KEY=sk-ant-your-api-key
AUTH_TOKEN=your-secure-random-token
```

**Optional (Git):**
```bash
GIT_SSH_KEY=-----BEGIN OPENSSH PRIVATE KEY-----...
# or
GIT_USERNAME=your-username
GIT_TOKEN=ghp_xxxxxxxxxxxx
```

**Optional (APNs):**
```bash
APPLE_TEAM_ID=your-team-id
APPLE_BUNDLE_ID=com.example.app
APPLE_KEY_ID=your-key-id
APPLE_P8_KEY=-----BEGIN PRIVATE KEY-----...
```

**Optional (Advanced):**
```bash
ANTHROPIC_BASE_URL=https://custom-api-endpoint.com
CONFIG_PATH=/app/config.yaml
```

### Git Configuration

To enable Git sync, edit `config.default.yaml` or create a custom `config.yaml`:

```yaml
git:
  enabled: true
  repo_url: git@github.com:your-username/Prime-Vault.git
  user_name: "Prime Agent"
  user_email: "prime@local"
  auth:
    method: ssh  # or "https"
```

Then set credentials in `.env`:

**SSH (recommended):**
```bash
GIT_SSH_KEY="$(cat ~/.ssh/id_ed25519)"
```

**HTTPS:**
```bash
GIT_USERNAME=your-username
GIT_TOKEN=ghp_xxxxxxxxxxxx
```

---

## API Reference

### Health Check

```http
GET /health
```

**Response:**
```json
{
  "status": "ok",
  "git_enabled": true
}
```

### Capture Thought

```http
POST /capture
Authorization: Bearer {AUTH_TOKEN}
Content-Type: application/json
```

**Request Body:**
```json
{
  "text": "Raw thought or transcription",
  "source": "iphone",
  "input": "voice",
  "captured_at": "2026-01-04T21:30:45Z",
  "context": {
    "app": "shortcuts"
  }
}
```

**Fields:**
- `text` (required) - The captured text content
- `source` (required) - Device: `"iphone"`, `"ipad"`, or `"mac"`
- `input` (required) - Input method: `"voice"` or `"text"`
- `captured_at` (required) - ISO 8601 timestamp (UTC)
- `context.app` (required) - App context: `"prime"`, `"shortcuts"`, `"cli"`, or `"web"`
- `context.location` (optional) - `{"latitude": float, "longitude": float}`

**Response:**
```json
{
  "ok": true,
  "inbox_file": "Inbox/2026-01-04_21-30-45_iphone.md",
  "dump_id": "2026-01-04T21:30:45Z-iphone"
}
```

### Trigger Processing

```http
POST /api/processing/trigger
Authorization: Bearer {AUTH_TOKEN}
```

**Response:**
```json
{
  "status": "started",
  "message": "Processing started"
}
```

or if already running:
```json
{
  "status": "already_running",
  "message": "Processing already in progress"
}
```

### Get Processing Status

```http
GET /api/processing/status
Authorization: Bearer {AUTH_TOKEN}
```

**Response:**
```json
{
  "is_running": false,
  "last_run": {
    "timestamp": "2026-01-04T21:32:15Z",
    "duration_seconds": 45.2,
    "cost_usd": 0.0234,
    "success": true
  },
  "unprocessed_count": 3
}
```

### Get Processing Queue

```http
GET /api/processing/queue
Authorization: Bearer {AUTH_TOKEN}
```

**Response:**
```json
{
  "count": 3,
  "dumps": [
    {
      "id": "2026-01-04T20:15:30Z-iphone",
      "file": ".prime/inbox/2026-W01/2026-01-04_20-15-30_iphone.md",
      "captured_at": "2026-01-04T20:15:30Z",
      "source": "iphone",
      "input": "voice",
      "preview": "Had an idea about the new feature..."
    }
  ]
}
```

### Git Operations

**Get Git Status:**
```http
GET /git/status
Authorization: Bearer {AUTH_TOKEN}
```

**Pull from Remote:**
```http
POST /git/pull
Authorization: Bearer {AUTH_TOKEN}
```

**Commit Changes:**
```http
POST /git/commit
Authorization: Bearer {AUTH_TOKEN}
Content-Type: application/json

{
  "message": "Commit message"
}
```

**Push to Remote:**
```http
POST /git/push
Authorization: Bearer {AUTH_TOKEN}
```

**Sync (Pull + Commit + Push):**
```http
POST /git/sync
Authorization: Bearer {AUTH_TOKEN}
```

### Push Notifications (APNs)

**Register Device:**
```http
POST /api/v1/push/register
Authorization: Bearer {AUTH_TOKEN}
Content-Type: application/json
```

**Request Body:**
```json
{
  "token": "device-push-token-hex",
  "device_type": "iphone",
  "device_name": "Michael's iPhone",
  "environment": "production"
}
```

**Send Notification:**
```http
POST /api/v1/notifications/send
Authorization: Bearer {AUTH_TOKEN}
Content-Type: application/json
```

**Request Body:**
```json
{
  "title": "Processing Complete",
  "body": "Your capture was processed successfully",
  "priority": "normal"
}
```

---

## Deployment

### Docker (Recommended)

**Quick start with Make:**

```bash
# Setup environment
cp .env.example .env
nano .env  # Add your credentials

# Start server
make dev-build

# View logs
make dev-logs

# Stop server
make dev-down
```

**Manual docker-compose:**

```bash
docker compose up --build -d
docker compose logs -f
```

**Using Docker directly:**

```bash
docker build -t primeagent:latest .

docker run -d \
  --name primeagent \
  -p 8000:8000 \
  --env-file .env \
  -v primeagent_vault:/vault \
  -v primeagent_claude:/home/prime/.claude \
  -v primeagent_data:/data \
  primeagent:latest
```

### Production Considerations

**Reverse Proxy (Recommended):**

Use Nginx or Caddy for:
- SSL/TLS termination
- Rate limiting
- Access control
- Custom domain

**Backups:**

Regularly backup Docker volumes:
```bash
# Backup vault
docker run --rm \
  -v primeagent_vault:/vault \
  -v $(pwd):/backup \
  alpine tar czf /backup/vault-backup.tar.gz -C /vault .

# Restore vault
docker run --rm \
  -v primeagent_vault:/vault \
  -v $(pwd):/backup \
  alpine tar xzf /backup/vault-backup.tar.gz -C /vault
```

**Monitoring:**
- Health endpoint: `GET /health`
- Processing status: `GET /api/processing/status`
- Docker logs: `docker compose logs -f primeagent`

**Security:**
- Always use HTTPS in production
- Rotate `AUTH_TOKEN` regularly
- Use SSH keys (not HTTPS tokens) for Git
- Restrict network access to trusted IPs
- Consider VPN or Tailscale for remote access

---

## Development

### Local Development Setup

```bash
# Clone repository
git clone https://github.com/prime-system/prime-agent.git
cd prime-agent

# Setup environment
cp .env.example .env
nano .env  # Add credentials

# Install dependencies (Python 3.11+)
pip install -r requirements.txt
pip install -e ".[dev]"

# Run development server
CONFIG_PATH=$(pwd)/config.default.yaml \
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Development Commands

See `make help` for all commands:

```bash
# Docker development
make dev              # Start dev server
make dev-build        # Rebuild and start
make dev-logs         # Follow logs
make dev-shell        # Shell into container

# Code quality
make lint             # Run ruff linter
make lint-fix         # Auto-fix issues
make format           # Format code
make type-check       # Run mypy
make test             # Run tests
make check            # Run all checks

# Cleanup
make dev-down         # Stop containers
make clean            # Remove cache files
```

### Running Tests

```bash
# Run all tests
make test
# or
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test
pytest tests/test_vault.py -v

# Run in Docker
make dev-shell
pytest
```

### Project Structure

```
PrimeAgent/
├── app/
│   ├── main.py              # FastAPI application
│   ├── config.py            # Configuration loading
│   ├── dependencies.py      # FastAPI dependencies
│   ├── version.py           # Version info
│   ├── api/                 # API endpoints
│   │   ├── capture.py       # Capture endpoint
│   │   ├── processing.py    # Processing control
│   │   ├── push.py          # Push notifications
│   │   ├── git.py           # Git operations
│   │   ├── files.py         # File operations
│   │   ├── chat.py          # Agent chat
│   │   ├── claude_sessions.py  # Session management
│   │   └── config.py        # Config API
│   ├── models/              # Pydantic models
│   │   ├── capture.py
│   │   ├── vault_config.py
│   │   └── ...
│   ├── services/            # Business logic
│   │   ├── agent.py         # Claude Agent SDK
│   │   ├── worker.py        # Processing worker
│   │   ├── vault.py         # Vault management
│   │   ├── git.py           # Git operations
│   │   ├── inbox.py         # Inbox operations
│   │   ├── title_generator.py  # AI title generation
│   │   └── ...
│   ├── prompts/             # Agent prompts
│   │   └── processCapture.md
│   └── utils/               # Utilities
├── tests/                   # Test suite
├── scripts/                 # Helper scripts
│   ├── entrypoint.sh        # Docker entrypoint
│   └── parse_config.py
├── .env.example             # Environment template
├── .gitignore               # Git ignore rules
├── config.default.yaml      # Default configuration
├── config.example.yaml      # Configuration examples
├── docker-compose.yml       # Docker orchestration
├── Dockerfile               # Container definition
├── Makefile                 # Development commands
├── pyproject.toml           # Python project config
├── requirements.txt         # Dependencies
├── CLAUDE.md                # Development guide
├── VAULT_CONFIG.md          # Vault configuration docs
└── README.md                # This file
```

---

## Vault Structure

PrimeAgent organizes notes into a Zettelkasten structure:

```
vault/
├── .prime/
│   ├── settings.yaml        # Vault configuration (optional)
│   ├── inbox/              # Captured thoughts
│   │   └── 2026-W01/       # Weekly subfolders (optional)
│   └── logs/               # Processing run logs
├── .claude/
│   └── commands/           # Custom agent prompts (optional)
│       └── processCapture.md
├── Daily/                  # Daily synthesis notes
├── Notes/                  # Atomic notes with links
├── Projects/               # Project-centric notes
├── Tasks/                  # Extracted actionable items
└── Questions/              # Open questions for review
```

**Note:** Only `.prime/` directory is created automatically. All other folders (Daily, Notes, Projects, etc.) are created by the agent during processing based on your vault's needs.

---

## Vault Configuration

**Customize how PrimeAgent stores captures in your vault.**

Create `.prime/settings.yaml` in your vault root to configure:
- Inbox folder name (e.g., "07-Inbox" for Obsidian)
- Weekly subfolders for organization
- Filename patterns (timestamps, AI titles, or both)

### Quick Example

```yaml
# /vault/.prime/settings.yaml
inbox:
  folder: "07-Inbox"
  weekly_subfolders: true
  file_pattern: "{year}-{month}-{day}_{hour}-{minute}-{second}_{source}.md"
```

**Result:** `07-Inbox/2026-W01/2026-01-04_21-30-45_iphone.md`

### AI-Generated Titles

Use `{title}` in your pattern for smart filenames:

```yaml
file_pattern: "{title}.md"
# or
file_pattern: "{year}-{month}-{day}_{title}.md"
```

**Example:**
- Capture: "Meeting with dev team about auth system"
- Filename: `meeting-with-dev-team.md` or `2026-01-04_meeting-with-dev-team.md`

Adds ~100-150ms per capture using Claude Haiku.

### Available Placeholders

`{year}`, `{month}`, `{day}`, `{hour}`, `{minute}`, `{second}`, `{source}`, `{iso_year}`, `{iso_week}`, `{title}`

### Full Documentation

See **[VAULT_CONFIG.md](./VAULT_CONFIG.md)** for complete documentation:
- All configuration options
- Pattern examples
- AI title generation details
- Best practices and tips
- Troubleshooting guide

### Default Configuration

Without `.prime/settings.yaml`, PrimeAgent uses:
```yaml
inbox:
  folder: ".prime/inbox"
  weekly_subfolders: true
  file_pattern: "{year}-{month}-{day}_{hour}-{minute}-{second}_{source}.md"
```

---

## Troubleshooting

### Environment Variable Issues

**Error: "Environment variable 'ANTHROPIC_API_KEY' not set"**

```bash
# Check .env file exists
cat .env

# Verify required variables
grep -E "ANTHROPIC_API_KEY|AUTH_TOKEN" .env

# Test docker-compose loads it
docker compose config | grep -A5 environment
```

### Container Exits Immediately

```bash
# Check logs
docker compose logs primeagent

# Common causes:
# 1. Missing ANTHROPIC_API_KEY or AUTH_TOKEN in .env
# 2. Invalid config.default.yaml syntax
# 3. Missing Python dependencies (rebuild: make dev-build)
```

### API Not Responding

```bash
# Check container status
docker compose ps

# Check logs
docker compose logs -f primeagent

# Restart
docker compose restart primeagent

# Rebuild if needed
make dev-build
```

### Git Sync Issues

**SSH authentication failed:**
```bash
# Test from within container
make dev-shell
ssh -T git@github.com

# Verify key is loaded
env | grep GIT_SSH_KEY | head -c 50
```

**HTTPS authentication failed:**
```bash
# Verify credentials in .env
grep -E "GIT_USERNAME|GIT_TOKEN" .env

# Enable git in config.default.yaml
grep -A5 "^git:" config.default.yaml
```

### Processing Not Working

**Agent not processing captures:**

```bash
# Check processing status
curl http://localhost:8000/api/processing/status \
  -H "Authorization: Bearer $AUTH_TOKEN"

# Check queue
curl http://localhost:8000/api/processing/queue \
  -H "Authorization: Bearer $AUTH_TOKEN"

# Manually trigger
curl -X POST http://localhost:8000/api/processing/trigger \
  -H "Authorization: Bearer $AUTH_TOKEN"

# Check logs
docker compose logs primeagent | grep -i process
```

**Budget exceeded:**
```bash
# Check budget setting
grep max_budget_usd config.default.yaml

# Increase budget (edit config.default.yaml)
# Then restart
docker compose restart primeagent
```

### Configuration Reloading

Both configs reload automatically on file changes:

```bash
# Server config (config.default.yaml)
docker compose restart primeagent

# Vault config (.prime/settings.yaml in vault)
# No restart needed - reloads on next access
```

---

## Project Status

**Current State:** Alpha (Experimental)

PrimeAgent is functional for personal use but still evolving rapidly. Expect:
- API changes without deprecation warnings
- Processing behavior refinements
- Occasional updates to vault structure

**Known Limitations:**
- Single-user only (no multi-user support planned)
- Processing can take several minutes for large captures
- No parallel processing (intentional design decision)
- Requires technical setup (Docker, API keys, Git)

---

## Roadmap

**Near-term:**
- Web UI for vault browsing and processing control
- Improved processing speed and context handling
- Better error recovery and retry logic
- Webhook support for processing events

**Future:**
- Automated daily/weekly synthesis
- Conversational API over entire knowledge base
- Multiple agent roles (summarizer, critic, planner)
- Integration with more capture apps

---

## Companion Projects

### PrimeClaude

Interactive SSH container with Claude Code CLI for real-time agent chat.

**Features:**
- SSH access to vault
- Claude Code CLI for interactive development
- Watch agent process dumps in real-time
- Base (~500MB) and Extended (~2.5GB) images

**Repository:** [github.com/prime-system/prime-claude](https://github.com/prime-system/prime-claude)

### Prime-App (Private)

iOS/macOS/iPadOS Swift app for frictionless capture.

**Features:**
- One-tap voice/text capture
- Shortcuts integration
- Push notification support
- Background sync

---

## Support

**Found a bug or have a question?**

Open an issue on [GitHub Issues](https://github.com/prime-system/prime-agent/issues).

**Note:** PrimeAgent is a personal project in early alpha. Response times may vary.

---

## License

PrimeAgent is released under the [Apache License 2.0](LICENSE).

---

## Philosophy

PrimeAgent is built on a simple belief:

**Friction kills ideas.**

The best knowledge systems get out of your way during capture and do the hard work of organization later. PrimeAgent is the "later" — the intelligent layer that transforms chaos into clarity.

---

**Built with Claude Agent SDK** | Self-hosted | Single-user | Your data, your control
