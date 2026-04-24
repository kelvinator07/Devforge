"""Local-dev backend: SQLite + env-var secrets + sentence-transformers + Chroma."""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from .interface import Backend, DB, Secrets, Embedder, Vectors


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path(os.environ.get("DEVFORGE_DATA_DIR", REPO_ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


class SQLiteDB(DB):
    """SQLite implementation.

    Accepts Postgres-flavored SQL that uses `:name` bind parameters (SQLite supports that).
    Rewrites PG-only syntax we actually use (BIGSERIAL, TIMESTAMPTZ, JSONB, `now()`) at
    migration time — see translate_pg_to_sqlite() in run_migrations.py. At query time both
    dialects are nearly identical.
    """

    def __init__(self, db_path: str | None = None):
        self.path = Path(db_path or (DATA_DIR / "devforge.db"))
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, isolation_level=None)  # autocommit
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        return c

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
        # Postgres uses `now()` and casts like `::jsonb` that SQLite doesn't.
        # Day-3 schema we wrote uses them only in defaults handled at migration time.
        with self._conn() as c:
            cur = c.execute(sql, params or {})
            if cur.description is None:  # DDL / non-returning DML
                return []
            return [dict(r) for r in cur.fetchall()]


class EnvSecrets(Secrets):
    """Map short secret names to env vars.

    openrouter-api-key             -> OPENROUTER_API_KEY
    github-app-private-key         -> GITHUB_APP_PRIVATE_KEY (raw PEM text)
                                      or GITHUB_APP_PRIVATE_KEY_PATH (file path)
    <any other name>               -> DEVFORGE_SECRET_<UPPER_WITH_UNDERSCORES>
    """

    def get(self, name: str) -> str:
        if name == "openrouter-api-key":
            v = os.environ.get("OPENROUTER_API_KEY")
            if not v:
                raise RuntimeError("OPENROUTER_API_KEY not set in env")
            return v
        if name == "github-app-private-key":
            if v := os.environ.get("GITHUB_APP_PRIVATE_KEY"):
                return v
            if path := os.environ.get("GITHUB_APP_PRIVATE_KEY_PATH"):
                return Path(path).expanduser().read_text()
            raise RuntimeError(
                "GITHUB_APP_PRIVATE_KEY (raw PEM) or GITHUB_APP_PRIVATE_KEY_PATH not set"
            )
        env_key = "DEVFORGE_SECRET_" + re.sub(r"[^A-Za-z0-9]", "_", name).upper()
        v = os.environ.get(env_key)
        if not v:
            raise RuntimeError(f"{env_key} not set in env for secret {name!r}")
        return v


class LocalEmbedder(Embedder):
    """sentence-transformers running on CPU. Same model as SageMaker (all-MiniLM-L6-v2)."""

    _model = None  # class-level cache

    def _ensure(self):
        if LocalEmbedder._model is None:
            from sentence_transformers import SentenceTransformer
            model_name = os.environ.get(
                "DEVFORGE_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
            )
            LocalEmbedder._model = SentenceTransformer(model_name)
        return LocalEmbedder._model

    def embed(self, text: str) -> list[float]:
        model = self._ensure()
        vec = model.encode(text, normalize_embeddings=True)
        return vec.tolist()


class ChromaVectors(Vectors):
    """Chroma in PersistentClient mode — per-index collection, file-backed at data/chroma/."""

    _client = None

    def __init__(self, persist_dir: str | None = None):
        self.persist_dir = Path(persist_dir or (DATA_DIR / "chroma"))
        self.persist_dir.mkdir(parents=True, exist_ok=True)

    def _get_client(self):
        if ChromaVectors._client is None:
            import chromadb
            ChromaVectors._client = chromadb.PersistentClient(path=str(self.persist_dir))
        return ChromaVectors._client

    def _coll(self, index: str):
        return self._get_client().get_or_create_collection(name=index)

    def put(self, index: str, key: str, vector: list[float], metadata: dict) -> None:
        flat = {k: v for k, v in metadata.items() if isinstance(v, (str, int, float, bool))}
        text = metadata.get("text", "")
        self._coll(index).upsert(
            ids=[key], embeddings=[vector], metadatas=[flat], documents=[text]
        )

    def put_many(self, index: str, items: list[dict]) -> None:
        if not items:
            return
        ids = [it["key"] for it in items]
        embeddings = [it["vector"] for it in items]
        metadatas = [
            {k: v for k, v in it["metadata"].items() if isinstance(v, (str, int, float, bool))}
            for it in items
        ]
        documents = [it["metadata"].get("text", "") for it in items]
        self._coll(index).upsert(
            ids=ids, embeddings=embeddings, metadatas=metadatas, documents=documents
        )

    def query(self, index: str, vector: list[float], k: int = 8) -> list[dict]:
        r = self._coll(index).query(query_embeddings=[vector], n_results=k)
        out = []
        for i, vid in enumerate(r["ids"][0]):
            out.append({
                "key": vid,
                "score": r["distances"][0][i],
                "metadata": r["metadatas"][0][i],
                "text": r["documents"][0][i] if r.get("documents") else "",
            })
        return out


class LocalBackend(Backend):
    def __init__(self):
        self.db = SQLiteDB()
        self.secrets = EnvSecrets()
        self.embedder = LocalEmbedder()
        self.vectors = ChromaVectors()
