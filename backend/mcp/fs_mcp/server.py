"""devforge-fs-mcp — scoped filesystem MCP (stdio).

Every tool resolves paths under `DEVFORGE_WORKTREE_ROOT` (defaults to the
current working directory). Any path that escapes the root raises
`PathOutOfScope` via an MCP error response — the agent sees a tool failure,
not a file it shouldn't see.

Tools:
  - read_file(path)         -> file contents (utf-8)
  - write_file(path, content, create_dirs=True) -> bytes written
  - list_dir(path=".")      -> sorted list of entries
  - delete_file(path)       -> removes a file (not directories)

Run:
    uv run python -m backend.mcp.fs_mcp.server
"""
from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("devforge-fs")


def _root() -> Path:
    root = os.environ.get("DEVFORGE_WORKTREE_ROOT") or os.getcwd()
    return Path(root).resolve()


def _resolve(path: str) -> Path:
    """Resolve `path` under the worktree root, or raise if it escapes."""
    root = _root()
    # Treat `path` as always relative to the root; drop leading slashes so the
    # agent can't pass absolute paths.
    rel = str(path).lstrip("/")
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError(f"PathOutOfScope: {path!r} escapes worktree root {root}")
    return candidate


@mcp.tool()
def read_file(path: str) -> str:
    """Read a text file relative to the worktree root. Returns its contents."""
    p = _resolve(path)
    if not p.exists():
        raise FileNotFoundError(f"no such file: {path}")
    if not p.is_file():
        raise ValueError(f"not a file: {path}")
    if p.stat().st_size > 1_000_000:
        raise ValueError(f"file too large ({p.stat().st_size} bytes > 1 MB)")
    return p.read_text(encoding="utf-8", errors="replace")


@mcp.tool()
def write_file(path: str, content: str, create_dirs: bool = True) -> int:
    """Write `content` to `path` inside the worktree. Creates parents if needed."""
    p = _resolve(path)
    if create_dirs:
        p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return len(content.encode("utf-8"))


@mcp.tool()
def list_dir(path: str = ".") -> list[str]:
    """List entries in a directory relative to the worktree root.

    Returns sorted names. Hidden dotfiles and common ignore dirs are filtered.
    """
    p = _resolve(path)
    if not p.exists():
        raise FileNotFoundError(f"no such directory: {path}")
    if not p.is_dir():
        raise ValueError(f"not a directory: {path}")
    ignore = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}
    items = sorted(
        e.name + ("/" if e.is_dir() else "")
        for e in p.iterdir()
        if e.name not in ignore
    )
    return items


@mcp.tool()
def delete_file(path: str) -> str:
    """Delete a single file inside the worktree. Refuses directories."""
    p = _resolve(path)
    if not p.exists():
        raise FileNotFoundError(f"no such file: {path}")
    if p.is_dir():
        raise ValueError("delete_file refuses directories")
    p.unlink()
    return f"deleted {path}"


if __name__ == "__main__":
    mcp.run()
