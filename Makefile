.PHONY: dev backend frontend test lint format

dev:
	@echo "Run 'make backend' and 'make frontend' in separate terminals."

backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && pnpm dev

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check .
	cd frontend && pnpm lint

format:
	cd backend && uv run ruff format .
	cd frontend && pnpm format

