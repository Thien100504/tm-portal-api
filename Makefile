.PHONY: up down logs migrate reset dev-backend dev-frontend test create-admin lint format build deploy

# ─────────────────────────────────────────────
# Development - Docker Services
# ─────────────────────────────────────────────

## Start development infrastructure (postgres, redis, rabbitmq)
up:
	docker compose -f docker/docker-compose.dev.yml up -d

## Stop development infrastructure
down:
	docker compose -f docker/docker-compose.dev.yml down

## Follow logs of development infrastructure
logs:
	docker compose -f docker/docker-compose.dev.yml logs -f

## Reset: destroy volumes, recreate, and run migrations
reset:
	docker compose -f docker/docker-compose.dev.yml down -v
	docker compose -f docker/docker-compose.dev.yml up -d
	Timeout /T 5 /Nobreak >NUL 2>&1 || sleep 5
	alembic upgrade head

# ─────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────

## Run database migrations
migrate:
	alembic upgrade head

## Create admin user
create-admin:
	python -m scripts.create_admin

# ─────────────────────────────────────────────
# Development Servers
# ─────────────────────────────────────────────

## Start backend dev server (FastAPI with hot reload)
dev-backend:
	.venv\Scripts\activate && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

## Start AI worker
dev-ai-worker:
	.venv\Scripts\activate && python -m app.workers.ai_worker

## Start Automation worker
dev-automation-worker:
	.venv\Scripts\activate && python -m app.workers.automation_worker

# ─────────────────────────────────────────────
# Testing & Quality
# ─────────────────────────────────────────────

## Run backend tests
test:
	pytest -v

## Run linter
lint:
	ruff check .

## Auto-format code
format:
	ruff format .

# ─────────────────────────────────────────────
# Production
# ─────────────────────────────────────────────

## Build all production containers
build:
	docker compose --env-file .env -f docker/docker-compose.yml build

## Deploy production stack
deploy:
	docker compose --env-file .env -f docker/docker-compose.yml up -d

## Stop production stack
deploy-down:
	docker compose --env-file .env -f docker/docker-compose.yml down
