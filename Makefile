.PHONY: dev up down logs test lint migrate

dev:
	uv run uvicorn services.core.app.main:app --reload --host 0.0.0.0 --port 8000

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

test:
	uv run pytest -q

lint:
	uv run ruff check .

migrate:
	docker compose run --rm api alembic upgrade head

