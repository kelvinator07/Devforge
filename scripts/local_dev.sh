#!/usr/bin/env bash
# DevForge local dev bootstrap.
#
# Usage:
#   ./scripts/local_dev.sh setup    # install deps + run migrations + sanity-check secrets
#   ./scripts/local_dev.sh serve    # run the control-plane FastAPI on :8001 (reload)
#   ./scripts/local_dev.sh smoke    # run the worker OpenRouter + embed smoke tests
#   ./scripts/local_dev.sh onboard  # guided tenant onboarding (interactive)
#
# Reads devforge/.env.local (create from .env.example).

set -euo pipefail

cd "$(dirname "$0")/.."
export DEVFORGE_BACKEND=local

if [[ -f .env.local ]]; then
  # shellcheck disable=SC1091
  source .env.local
  export $(grep -v '^#' .env.local | grep '=' | cut -d= -f1)
fi

cmd="${1:-}"

case "$cmd" in
  setup)
    echo "== installing deps (local + aws extras) =="
    uv sync --extra all
    echo
    echo "== running migrations (SQLite) =="
    uv run python -m backend.database.run_migrations
    echo
    echo "== sanity-checking secrets =="
    uv run python -c "
from backend.common import get_backend
b = get_backend()
try: b.secrets.get('openrouter-api-key'); print('OPENROUTER_API_KEY: OK')
except Exception as e: print(f'OPENROUTER_API_KEY: MISSING ({e})')
try: b.secrets.get('github-app-private-key'); print('GITHUB_APP_PRIVATE_KEY: OK')
except Exception as e: print(f'GITHUB_APP_PRIVATE_KEY: MISSING ({e})')
"
    echo
    echo "Next: ./scripts/local_dev.sh serve"
    ;;

  serve)
    echo "== starting control plane on http://localhost:8001 =="
    # --reload watches the cwd. Without excludes, it sees the orchestrator
    # writing into data/worktrees/ mid-job and kills the in-flight worker.
    # Watch only the actual source trees + scope the watch to .py files.
    exec uv run uvicorn backend.control_plane.main:app \
      --reload --host 0.0.0.0 --port 8001 \
      --reload-dir backend --reload-dir scripts \
      --reload-include "*.py"
    ;;

  smoke)
    echo "== worker :: openrouter smoke =="
    DEVFORGE_WORKER_MODE=smoke uv run python -m backend.worker.crew
    echo
    echo "== worker :: embed + vector smoke =="
    DEVFORGE_WORKER_MODE=embed uv run python -m backend.worker.crew
    ;;

  onboard)
    exec uv run python scripts/install_github_app.py
    ;;

  *)
    echo "usage: $0 {setup|serve|smoke|onboard}"
    exit 1
    ;;
esac
