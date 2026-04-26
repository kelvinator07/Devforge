"""Pytest config + shared fixtures.

- Adds the repo root to sys.path so `from backend.x import ...` works
  without an editable install.
- Provides a `tmp_db` fixture that points DEVFORGE_DB_PATH at a per-test
  temp SQLite, runs all migrations against it, and tears down via tmp_path.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Per-test SQLite at tmp_path/devforge.db with all migrations applied."""
    db_path = tmp_path / "devforge.db"
    monkeypatch.setenv("DEVFORGE_BACKEND", "local")
    monkeypatch.setenv("DEVFORGE_DB_PATH", str(db_path))

    # Reset the cached backend singleton so each test sees a fresh DB.
    import backend.common as common
    if hasattr(common, "_backend"):
        monkeypatch.setattr(common, "_backend", None, raising=False)

    from backend.database.run_migrations import MIGRATIONS_DIR, apply_local
    apply_local(sorted(MIGRATIONS_DIR.glob("*.sql")))
    yield db_path
