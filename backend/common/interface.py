"""Abstract interfaces for the backend-adapter pattern.

Both local and aws implementations provide a Backend with four facets:
  - db        : relational store (Postgres via Aurora Data API / SQLite)
  - secrets   : key-value secret store (Secrets Manager / env vars)
  - embedder  : text -> vector (SageMaker / sentence-transformers)
  - vectors   : vector store (S3 Vectors / Chroma)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DB(ABC):
    """Minimal SQL interface. Both backends use `:name` parameter binding."""

    @abstractmethod
    def execute(self, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
        """Run `sql` with `params` and return rows as list-of-dict."""


class Secrets(ABC):
    @abstractmethod
    def get(self, name: str) -> str:
        """Return the secret value. `name` is a short identifier like 'openrouter-api-key'."""


class Embedder(ABC):
    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Return the embedding vector for `text` (384 dims for all-MiniLM-L6-v2)."""


class Vectors(ABC):
    @abstractmethod
    def put(self, index: str, key: str, vector: list[float], metadata: dict) -> None:
        """Upsert a vector under `key` in the given `index`."""

    @abstractmethod
    def query(self, index: str, vector: list[float], k: int = 8) -> list[dict]:
        """Return top-`k` nearest records as list of {key, score, metadata}."""


class Backend(ABC):
    db: DB
    secrets: Secrets
    embedder: Embedder
    vectors: Vectors
