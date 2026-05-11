.PHONY: install lint type test test-unit test-int up down migrate clean help

install:
	uv sync

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

format:
	uv run ruff check --fix src tests
	uv run ruff format src tests

type:
	uv run mypy src

test-unit:
	uv run pytest tests/unit -v

test-int:
	uv run pytest tests/integration -v

test-e2e:
	uv run pytest tests/e2e -v

test:
	uv run pytest tests -v

up:
	docker compose up -d --build

down:
	docker compose down -v

migrate:
	uv run alembic upgrade head

clean:
	uv run python -m webhook_inspector.jobs.cleaner

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'
