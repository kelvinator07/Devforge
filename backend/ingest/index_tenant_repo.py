"""Clone a tenant repo, AST-chunk it, embed each chunk, write to the vector store.

Local mode:   Chroma collection `tenant_<id>_codebase`
AWS mode:     S3 Vectors index       `tenant-<id>-codebase`
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from backend.common import get_backend
from backend.ingest.chunker import Chunk, chunk_file, walk_repo


# Event callback signature: (event_name, payload_dict) -> None.
EventCallback = Callable[[str, dict], None]


def index_name_for(tenant_id: int) -> str:
    # S3 Vectors index names allow only lowercase letters, digits, and
    # hyphens (no underscores). Chroma is more permissive so hyphens
    # work for both backends.
    return f"tenant-{tenant_id}-codebase"


def clone_with_token(repo_full_name: str, installation_token: str, dest: Path) -> None:
    """Shallow-clone a repo using a GitHub App installation token."""
    url = f"https://x-access-token:{installation_token}@github.com/{repo_full_name}.git"
    subprocess.run(
        ["git", "clone", "--depth", "1", url, str(dest)],
        check=True,
        capture_output=True,
    )


def index_repo(
    tenant_id: int,
    repo_full_name: str,
    installation_token: str,
    repo_root: Path | None = None,
    on_event: EventCallback | None = None,
) -> dict:
    """Main entrypoint. Returns a stats dict.

    If `repo_root` is given, skip cloning and index the local checkout (useful for tests).
    `on_event(name, payload)`, when supplied, is called at each phase boundary so callers
    (e.g. the spawned `run_index_job` process) can persist progress to a DB or stream
    it over SSE. CLI usage that omits the callback is unaffected.
    """
    on = on_event or (lambda *_args, **_kwargs: None)

    backend = get_backend()
    index = index_name_for(tenant_id)

    with tempfile.TemporaryDirectory(prefix="devforge-index-") as td:
        if repo_root is None:
            repo_root = Path(td) / "repo"
            on("clone_started", {"repo": repo_full_name})
            clone_with_token(repo_full_name, installation_token, repo_root)
            on("clone_complete", {"repo": repo_full_name})
            cleanup = True
        else:
            cleanup = False

        files = walk_repo(repo_root)
        print(f"[index] {repo_full_name}: {len(files)} indexable files", flush=True)
        on("walk_complete", {"file_count": len(files)})

        chunks_by_file: dict[str, list[Chunk]] = {}
        total_chunks = 0
        for p in files:
            rel = str(p.relative_to(repo_root))
            cs = chunk_file(p, rel)
            if cs:
                chunks_by_file[rel] = cs
                total_chunks += len(cs)

        print(f"[index] {total_chunks} chunks across {len(chunks_by_file)} files", flush=True)
        on("chunking_complete", {"files": len(chunks_by_file), "chunks_total": total_chunks})

        # Embed + upsert in batches of 32 (keeps Chroma/S3V calls fast).
        items: list[dict] = []
        done = 0
        batch_size = 32
        for rel, cs in chunks_by_file.items():
            for c in cs:
                vec = backend.embedder.embed(c.text)
                items.append({
                    "key": c.key(repo_full_name, tenant_id),
                    "vector": vec,
                    "metadata": {
                        "tenant_id": tenant_id,
                        "repo": repo_full_name,
                        "file": c.file,
                        "start_line": c.start_line,
                        "end_line": c.end_line,
                        "kind": c.kind,
                        "name": c.name,
                        "sha": c.sha(),
                        # Chroma uses the `text` document field; S3 Vectors metadata also carries it.
                        "text": c.text[:8000],
                    },
                })
                if len(items) >= batch_size:
                    backend.vectors.put_many(index, items)
                    done += len(items)
                    items = []
                    print(f"[index]   {done}/{total_chunks} embedded", flush=True)
                    on("embedding_progress", {"done": done, "total": total_chunks})
        if items:
            backend.vectors.put_many(index, items)
            done += len(items)
            on("embedding_progress", {"done": done, "total": total_chunks})

        on("embedding_complete", {"chunks_written": done})

        if cleanup and repo_root.exists():
            pass  # handled by tempdir context

    return {
        "tenant_id": tenant_id,
        "repo": repo_full_name,
        "index": index,
        "files_indexed": len(chunks_by_file),
        "chunks_written": total_chunks,
    }


def search_codebase(tenant_id: int, query: str, k: int = 8) -> list[dict]:
    """Embed `query` and return top-`k` codebase chunks for this tenant."""
    backend = get_backend()
    vec = backend.embedder.embed(query)
    return backend.vectors.query(index_name_for(tenant_id), vec, k=k)
