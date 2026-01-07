# PrimeAI: FastAPI Server Container (Python-only)
FROM python:3.14-slim

# Build arguments
ARG APP_USER=prime
ARG APP_UID=1000
ARG APP_GID=1000

# Environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    openssh-client \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv (Python package manager)
RUN pip install --no-cache-dir uv && uv --version

# Create non-root user
RUN groupadd --gid ${APP_GID} ${APP_USER} \
    && useradd --uid ${APP_UID} --gid ${APP_GID} --shell /bin/bash --create-home ${APP_USER}

# Create directories with proper permissions
RUN mkdir -p /home/${APP_USER}/.claude /home/${APP_USER}/.ssh /data/apn \
    && chown -R ${APP_USER}:${APP_USER} /home/${APP_USER} /data

# Install Python dependencies from lock file
COPY pyproject.toml uv.lock .
RUN uv sync --frozen --no-dev

# Copy application code and configuration template
COPY --chown=${APP_USER}:${APP_USER} app/ app/
COPY --chown=${APP_USER}:${APP_USER} scripts/ /app/scripts/
COPY --chown=${APP_USER}:${APP_USER} config.default.yaml /app/config.default.yaml
COPY --chown=root:root scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Switch to non-root user to configure Git
USER ${APP_USER}

# Configure Git defaults (can be overridden via environment)
RUN git config --global user.name "Prime AI" \
    && git config --global user.email "ai@prime.local" \
    && git config --global init.defaultBranch main

# Switch back to root for entrypoint
USER root

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD bash -c "cd /app && uv run python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\"" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
