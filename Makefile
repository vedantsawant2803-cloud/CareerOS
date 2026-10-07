# ============================================================================
# CareerOS — task runner
# All commands are documented in README.md.
# ============================================================================

COMPOSE        := docker compose
COMPOSE_DEV    := docker compose -f docker-compose.yml -f docker-compose.dev.yml
PY             := python
BACKEND_SERVICE := backend

.PHONY: install dev up down logs seed test lint format eval clean help

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Install backend + dev dependencies locally
	$(PY) -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt

dev: ## Start the full stack with reload-friendly development settings
	$(COMPOSE_DEV) up --build

up: ## Build and start the full stack (qdrant, backend, frontend)
	$(COMPOSE) up --build -d

down: ## Stop and remove the stack
	$(COMPOSE) down

logs: ## Tail logs from all services
	$(COMPOSE) logs -f --tail=200

seed: ## Index the sample documents into Qdrant
	$(COMPOSE) exec $(BACKEND_SERVICE) python scripts/seed_data.py

test: ## Run the test suite (no live LLM / Qdrant required)
	$(PY) -m pytest tests -q

lint: ## Run ruff lint checks
	$(PY) -m ruff check backend/app scripts tests

format: ## Auto-fix lint issues and format imports
	$(PY) -m ruff check --fix backend/app scripts tests
	$(PY) -m ruff format backend/app scripts tests

eval: ## Run the retrieval/answer evaluation suite
	$(PY) scripts/run_eval.py

clean: ## Remove local caches, generated logs and Qdrant storage
	rm -rf .pytest_cache .ruff_cache .mypy_cache
	rm -rf qdrant_storage logs
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	$(COMPOSE) down -v --remove-orphans
