.PHONY: help up down logs test lint fmt typecheck api reset-db

help:
	@echo "up         start db, redis, minio"
	@echo "api        run the API with reload"
	@echo "test       run the backend test suite"
	@echo "lint       ruff check"
	@echo "fmt        ruff format"
	@echo "typecheck  mypy"
	@echo "reset-db   DESTRUCTIVE: drop volumes and re-init schemas"

up:
	docker compose up -d db redis minio

down:
	docker compose down

logs:
	docker compose logs -f api

api:
	cd backend && uvicorn app.main:app --reload --port 8000

test:
	cd backend && pytest -q

lint:
	cd backend && ruff check .

fmt:
	cd backend && ruff format .

typecheck:
	cd backend && mypy app

reset-db:
	@echo "This deletes all local data. Ctrl-C to abort."
	@sleep 5
	docker compose down -v && docker compose up -d db
