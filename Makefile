.PHONY: setup dev test lint format health seed demo typecheck

PYTHONPATH := apps/api:apps/worker:packages/domain:packages/db:packages/providers:packages/eval
COMPOSE := docker compose -f infra/docker-compose.yml
export PYTHONPATH

setup:
	uv sync --group dev
	npx --yes pnpm@9.15.0 install

dev:
	$(COMPOSE) up --build

test:
	uv run pytest
	npx --yes pnpm@9.15.0 --filter recoverai-web test

lint:
	uv run ruff check apps tests packages
	uv run ruff format --check apps tests packages
	uv run mypy
	npx --yes pnpm@9.15.0 --filter recoverai-web lint
	npx --yes pnpm@9.15.0 --filter recoverai-web typecheck

format:
	uv run ruff check --fix apps tests packages
	uv run ruff format apps tests packages

typecheck:
	uv run mypy
	npx --yes pnpm@9.15.0 --filter recoverai-web typecheck

health:
	uv run python scripts/health.py

seed:
	uv run alembic upgrade head
	uv run python scripts/seed.py

migrate:
	uv run alembic upgrade head

demo:
	@echo "POST /v1/simulation/scenarios G-O plus /v1/recovery-cases/{id}/process, /actions/execute, and /verify."
