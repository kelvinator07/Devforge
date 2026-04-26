# DevForge — local development front door.
#
# `make help` lists everything. The Docker compose stack runs the control plane
# (FastAPI on :8001) + frontend (Next.js on :3000); workers spawn as
# subprocesses inside the control-plane container per ticket.
#
# scripts/local_dev.sh is still callable for non-Docker workflows; this file is
# the documented path going forward.

DC := docker compose
CP := $(DC) exec control-plane
TENANT ?= 1

.DEFAULT_GOAL := help

# ---- Discovery ----------------------------------------------------------

help: ## List the targets in this Makefile.
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' \
		| sort
.PHONY: help

# ---- One-shot setup -----------------------------------------------------

setup: ## Build images, install Python + Node deps, run DB migrations.
	$(DC) build
	$(DC) run --rm control-plane uv sync
	$(DC) run --rm frontend npm install
	$(MAKE) migrate
	@echo
	@echo "Setup complete. Next:"
	@echo "  make dev        # bring up the stack"
	@echo "  make seed       # populate + index the demo repo"
.PHONY: setup

migrate: ## Apply all SQL migrations against the local SQLite DB.
	$(DC) run --rm control-plane uv run python -m backend.database.run_migrations
.PHONY: migrate

# ---- Lifecycle ----------------------------------------------------------

dev: ## Start control plane (:8001) + frontend (:3000) with hot-reload.
	$(DC) up -d
	@echo "control-plane: http://localhost:8001"
	@echo "frontend:      http://localhost:3000"
	@echo "tail logs:     make logs"
.PHONY: dev

up: dev ## Alias for `make dev`.
.PHONY: up

stop: ## Stop the stack (preserves volumes + data/).
	$(DC) down
.PHONY: stop

restart: ## Restart both services without nuking volumes.
	$(DC) restart
.PHONY: restart

logs: ## Tail logs from all services.
	$(DC) logs -f
.PHONY: logs

cp-logs: ## Tail just the control plane.
	$(DC) logs -f control-plane
.PHONY: cp-logs

fe-logs: ## Tail just the frontend.
	$(DC) logs -f frontend
.PHONY: fe-logs

# ---- Inspection ---------------------------------------------------------

shell: ## Drop into a bash shell inside the control-plane container.
	$(CP) bash
.PHONY: shell

ps: ## Show service status.
	$(DC) ps
.PHONY: ps

# ---- Demo repo + RAG index ----------------------------------------------

seed: ## Populate the GitHub demo repo and build its RAG index. TENANT=1 by default.
	$(CP) uv run python -m scripts.populate_demo_repo $(TENANT)
	$(CP) uv run python -m scripts.index_repo $(TENANT)
.PHONY: seed

# ---- Tickets ------------------------------------------------------------

ticket: ## Run the default demo ticket end-to-end through the crew. TENANT=1 by default.
	$(CP) uv run python -m scripts.run_ticket $(TENANT)
.PHONY: ticket

# ---- Verification -------------------------------------------------------

test: ## Run unit tests — pytest (backend) + vitest (frontend).
	uv run pytest -q
	cd frontend && npm test
.PHONY: test

test-backend: ## Run only backend pytest suite.
	uv run pytest -q
.PHONY: test-backend

test-frontend: ## Run only frontend vitest suite.
	cd frontend && npm test
.PHONY: test-frontend

redteam: ## Deterministic red-team — 9 guardrail tests, $0 in LLM credits.
	$(CP) uv run python -m scripts.redteam
.PHONY: redteam

redteam-live: ## Live red-team — 3 LLM-driven attacks, ~$0.30 in OpenRouter credits.
	$(CP) uv run python -m scripts.redteam_live $(TENANT)
.PHONY: redteam-live

verify-mcps: ## Smoke-check fs-mcp + sandbox-mcp scope enforcement.
	$(CP) uv run python -m scripts.verify_mcps
.PHONY: verify-mcps

cost: ## Per-job cost dashboard.
	$(CP) uv run python -m backend.cost.dashboard --tenant $(TENANT)
.PHONY: cost

# ---- Cleanup ------------------------------------------------------------

clean: ## Stop, remove volumes, and wipe data/. Re-run `make setup` after.
	$(DC) down -v
	rm -rf data/worktrees data/job_logs data/devforge.db data/chroma
	@echo "Cleaned. Run `make setup` to rebuild."
.PHONY: clean

rebuild: ## Force rebuild images without using cache.
	$(DC) build --no-cache
.PHONY: rebuild
