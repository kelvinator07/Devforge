"""CLI: semantic search against a tenant's indexed codebase.

Usage:
    uv run python -m scripts.search_codebase <tenant_id> "<query>"
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env.local", override=False)
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit('usage: search_codebase.py <tenant_id> "<query>"')
    tenant_id = int(sys.argv[1])
    query = " ".join(sys.argv[2:])

    from backend.ingest.index_tenant_repo import search_codebase

    hits = search_codebase(tenant_id, query, k=5)
    print(f"query: {query}\n")
    for i, h in enumerate(hits, 1):
        meta = h.get("metadata", {})
        print(f"  [{i}] score={h.get('score'):.4f}  {meta.get('file')}:L{meta.get('start_line')}-{meta.get('end_line')}  ({meta.get('kind')} {meta.get('name')})")
        txt = (h.get("text") or meta.get("text") or "").splitlines()
        preview = "\n      | ".join(txt[:4])
        if preview:
            print(f"      | {preview}")
        print()


if __name__ == "__main__":
    main()
