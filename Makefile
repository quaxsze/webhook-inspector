.PHONY: install lint type test test-unit test-int test-e2e up down migrate clean help

install: ## Install dependencies via uv
	uv sync

lint: ## Run ruff lint + format check
	uv run ruff check src tests
	uv run ruff format --check src tests

format: ## Auto-fix and format with ruff
	uv run ruff check --fix src tests
	uv run ruff format src tests

type: ## Run mypy strict type-check
	uv run mypy src

test-unit: ## Run unit tests
	uv run pytest tests/unit -v

coverage: ## Run tests with coverage report (terminal + HTML in htmlcov/)
	uv run pytest tests --cov --cov-report=term-missing --cov-report=html

test-int: ## Run integration tests
	uv run pytest tests/integration -v

test-e2e: ## Run E2E tests
	uv run pytest tests/e2e -v

test: ## Run full pytest suite
	uv run pytest tests -v

up: ## Start docker-compose stack
	docker compose up -d --build

down: ## Stop docker-compose stack and remove volumes
	docker compose down -v

migrate: ## Run alembic migrations
	uv run alembic upgrade head

clean: ## Run cleanup job (delete expired endpoints)
	uv run python -m webhook_inspector.jobs.cleaner

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'
