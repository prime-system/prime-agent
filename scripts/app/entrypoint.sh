#!/bin/bash
set -e

echo "Prime AI (FastAPI Server) - Starting..."

# ============================================
# Configuration Loading
# ============================================

# Load configuration from config.yaml (with env var overrides)
CONFIG_FILE="${CONFIG_PATH:-/app/config.yaml}"
CONFIG_PARSER="/app/scripts/parse_config.py"

if [ -f "$CONFIG_PARSER" ]; then
    # Parse config.yaml and export variables
    # This sets: GIT_ENABLED, VAULT_REPO_URL, VAULT_PATH, WORKSPACE_PATH, etc.
    # Use uv run to ensure Python has access to installed dependencies (PyYAML)
    # Note: Don't redirect stderr to stdout, as uv build messages would be evaluated as shell commands
    if eval "$(cd /app && uv run python "$CONFIG_PARSER" "$CONFIG_FILE")"; then
        echo "Configuration loaded from $CONFIG_FILE"
    else
        echo "WARNING: Failed to parse config file, using defaults and env vars"
    fi
else
    echo "WARNING: Config parser not found at $CONFIG_PARSER"
    # Fallback to defaults
    VAULT_PATH="${VAULT_PATH:-/vault}"
    WORKSPACE_PATH="${WORKSPACE_PATH:-/workspace}"
    GIT_ENABLED="${GIT_ENABLED:-false}"
fi

# ============================================
# Notify Skill Setup
# ============================================

if [ -z "$PRIME_API_URL" ]; then
    if [ -n "$BASE_URL" ]; then
        PRIME_API_URL="${BASE_URL%/}"
    else
        PRIME_API_URL="http://localhost:8000"
    fi
    export PRIME_API_URL
fi

if [ -z "$PRIME_API_TOKEN" ] && [ -n "$AUTH_TOKEN" ]; then
    export PRIME_API_TOKEN="$AUTH_TOKEN"
fi

SKILLS_SRC="/app/skills"
CLAUDE_SKILLS_DIR="/home/prime/.claude/skills"

if [ -d "$SKILLS_SRC/notify-skill" ]; then
    mkdir -p "$CLAUDE_SKILLS_DIR"
    if [ ! -f "$CLAUDE_SKILLS_DIR/notify-skill/SKILL.md" ]; then
        echo "Installing notify skill..."
        cp -R "$SKILLS_SRC/notify-skill" "$CLAUDE_SKILLS_DIR/"
    fi

    chown -R prime:prime "$CLAUDE_SKILLS_DIR/notify-skill"
    chmod -R u+rwX,go+rX,go-w "$CLAUDE_SKILLS_DIR/notify-skill"

    if [ -f "$CLAUDE_SKILLS_DIR/notify-skill/notify.py" ]; then
        chmod +x "$CLAUDE_SKILLS_DIR/notify-skill/notify.py"
    fi
fi

# Only initialize Git if enabled
if [ "$GIT_ENABLED" = "true" ] || [ "$GIT_ENABLED" = "True" ]; then
    if [ -z "$VAULT_REPO_URL" ]; then
        echo "ERROR: Git enabled but repo_url not configured (check config.yaml or VAULT_REPO_URL env var)"
        exit 1
    fi

    echo "Git enabled - initializing vault repository..."

    # Configure SSH for Git if key is provided
    if [ -n "$GIT_SSH_KEY" ]; then
        echo "Configuring SSH key for Git..."
        mkdir -p /home/prime/.ssh

        # Write SSH key (handle both literal \n and actual newlines)
        printf '%b\n' "$GIT_SSH_KEY" > /home/prime/.ssh/id_ed25519
        chmod 600 /home/prime/.ssh/id_ed25519
        chown prime:prime /home/prime/.ssh/id_ed25519

        # Add GitHub/GitLab to known hosts
        ssh-keyscan -t ed25519 github.com >> /home/prime/.ssh/known_hosts 2>/dev/null || true
        ssh-keyscan -t ed25519 gitlab.com >> /home/prime/.ssh/known_hosts 2>/dev/null || true
        chown prime:prime /home/prime/.ssh/known_hosts 2>/dev/null || true
        chmod 600 /home/prime/.ssh/known_hosts
    fi

    # Configure Git credentials if using HTTPS
    if [ -n "$GIT_TOKEN" ] && [ -n "$GIT_USERNAME" ]; then
        echo "Configuring Git credentials..."
        su prime -c "git config --global credential.helper store"
        echo "https://${GIT_USERNAME}:${GIT_TOKEN}@github.com" > /home/prime/.git-credentials
        chmod 600 /home/prime/.git-credentials
        chown prime:prime /home/prime/.git-credentials
    fi

    # Configure Git user (from config.yaml or env vars)
    su prime -c "git config --global user.name '$GIT_USER_NAME'"
    su prime -c "git config --global user.email '$GIT_USER_EMAIL'"

    # Initialize vault repository (as prime user)
    if [ ! -d "$VAULT_PATH/.git" ]; then
        echo "Cloning vault repository from $VAULT_REPO_URL..."
        su prime -c "git clone '$VAULT_REPO_URL' '$VAULT_PATH'" || {
            echo "ERROR: Failed to clone repository"
            exit 1
        }
    else
        echo "Vault repository exists, pulling latest..."
        su prime -c "cd '$VAULT_PATH' && git pull --ff-only" || {
            echo "WARNING: Git pull failed, continuing with local state"
        }
    fi
else
    echo "Git disabled - running in local-only mode"

    # Ensure vault directory exists and set ownership
    mkdir -p "$VAULT_PATH"
    chown -R prime:prime "$VAULT_PATH"
fi

# ============================================
# Vault Structure Setup
# ============================================

# Ensure vault directory structure (in both modes)
# Fix ownership first in case volume was created by root
chown -R prime:prime "$VAULT_PATH"
# Only create .prime/ - all other folders created on-demand by Agent or user
su prime -c "mkdir -p '$VAULT_PATH/.prime'"

# ============================================
# Workspace Setup
# ============================================

echo "Setting up workspace directory at $WORKSPACE_PATH..."

# Ensure workspace directory exists
if [ ! -d "$WORKSPACE_PATH" ]; then
    mkdir -p "$WORKSPACE_PATH"
fi

# Set correct ownership
chown -R prime:prime "$WORKSPACE_PATH"
chmod -R u+rw,g+r,o-rwx "$WORKSPACE_PATH"

echo "Workspace directory ready at $WORKSPACE_PATH"

# ============================================
# Apple Push Notifications Setup
# ============================================

# Ensure /data/apn directory exists for devices.json
if [ -n "$APPLE_P8_KEY" ]; then
    echo "APNs enabled - ensuring data directory exists..."
    mkdir -p /data/apn
    chown prime:prime /data /data/apn
fi

# ============================================
# Permissions and Cleanup
# ============================================

# Fix permissions for all prime-owned files
chown -R prime:prime /home/prime

# Return to app directory before starting server
cd /app

echo "Starting FastAPI server on port 8000..."
exec su prime -c "cd /app && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000"
