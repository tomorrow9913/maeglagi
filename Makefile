.PHONY: dev backend frontend migrate migration test lint format

dev:
	@echo "Run 'make backend' and 'make frontend' in separate terminals."

backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && pnpm dev

migrate:
	cd backend && uv run alembic upgrade head

migration:
	cd backend && uv run alembic revision --autogenerate -m "$(name)"

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check .
	cd frontend && pnpm lint

format:
	cd backend && uv run ruff format .
	cd frontend && pnpm format
