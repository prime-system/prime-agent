.PHONY: help lint format type-check test test-cov coverage-report coverage-check clean install-dev pre-commit-install dev dev-build dev-down dev-logs dev-shell update-lock release release-push

help:
	@echo "Available commands:"
	@echo ""
	@echo "Development (Docker):"
	@echo "  make dev                Start dev server (docker compose up)"
	@echo "  make dev-build          Rebuild and start dev server"
	@echo "  make dev-down           Stop dev server"
	@echo "  make dev-logs           Follow dev server logs"
	@echo "  make dev-shell          Shell into running container"
	@echo ""
	@echo "Code Quality:"
	@echo "  make install-dev        Install dev dependencies with uv"
	@echo "  make pre-commit-install Install pre-commit hooks"
	@echo "  make lint               Run ruff linter"
	@echo "  make lint-fix           Run ruff linter with auto-fix"
	@echo "  make format             Format code with ruff"
	@echo "  make type-check         Run mypy type checker"
	@echo "  make test               Run pytest"
	@echo "  make test-cov           Run pytest with coverage report"
	@echo "  make coverage-report    Generate HTML coverage report"
	@echo "  make coverage-check     Check coverage meets 80%% threshold"
	@echo "  make check              Run all checks (lint + type-check + test)"
	@echo "  make update-lock        Update uv.lock with latest compatible versions"
	@echo "  make clean              Remove cache files"
	@echo ""
	@echo "Local Development (without Docker):"
	@echo "  make install-dev        Install dev dependencies with uv"
	@echo "  make lint               Run linter on local code"
	@echo "  make test               Run tests locally"
	@echo ""
	@echo "Release:"
	@echo "  make release VERSION=X.Y.Z       Create new release (update version, commit, tag)"
	@echo "  make release-push VERSION=X.Y.Z  Create and push new release"

install-dev:
	uv sync

pre-commit-install: install-dev
	uv run pre-commit install

lint:
	uv run ruff check app tests

lint-fix:
	uv run ruff check --fix app tests

format:
	uv run ruff format app tests

type-check:
	uv run mypy app tests

test:
	uv run pytest

test-cov:
	uv run pytest --cov=app --cov-report=html --cov-report=term

coverage-report:
	uv run pytest --cov=app --cov-report=html
	@echo "Coverage report generated in htmlcov/index.html"

coverage-check:
	uv run pytest --cov=app --cov-report=term --cov-fail-under=80

check: lint type-check test

update-lock:
	uv lock --upgrade

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache __pycache__ .coverage htmlcov
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# Docker dev commands
dev:
	docker compose up

dev-build:
	docker compose up --build

dev-down:
	docker compose down

dev-logs:
	docker compose logs -f

dev-shell:
	docker compose exec primeai bash

# Release commands
release:
ifndef VERSION
	@echo "Error: VERSION not specified"
	@echo "Usage: make release VERSION=0.2.0"
	@exit 1
endif
	@./scripts/create-release.sh $(VERSION)

release-push:
ifndef VERSION
	@echo "Error: VERSION not specified"
	@echo "Usage: make release-push VERSION=0.2.0"
	@exit 1
endif
	@./scripts/create-release.sh $(VERSION) --push
