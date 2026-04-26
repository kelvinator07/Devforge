"""Tests for backend.ingest.chunker — AST + line-window chunking + repo walk.

We assert chunk *boundaries and metadata*, not parser internals (Python's
`ast` is the source of truth for line numbers; we just verify our adapter
preserves them).
"""
from __future__ import annotations

from pathlib import Path

from backend.ingest.chunker import (
    Chunk,
    chunk_file,
    chunk_python,
    should_skip_file,
    walk_repo,
)


# --- Python AST chunking ---


def test_python_function_extracted(tmp_path: Path) -> None:
    f = tmp_path / "demo.py"
    f.write_text(
        "def foo():\n"
        "    return 1\n"
        "\n"
        "class Bar:\n"
        "    def baz(self):\n"
        "        return 2\n"
    )
    chunks = chunk_file(f, "demo.py")
    kinds = {c.kind for c in chunks}
    names = {c.name for c in chunks}

    assert "function" in kinds and "foo" in names
    assert "class" in kinds and "Bar" in names
    # Methods are emitted as their own chunks, qualified.
    assert "method" in kinds and "Bar.baz" in names


def test_python_module_level_chunk(tmp_path: Path) -> None:
    """Top-level imports/constants must surface as a 'module' chunk."""
    f = tmp_path / "mod.py"
    f.write_text(
        "import os\n"
        "VERSION = '1.0'\n"
        "\n"
        "def greet(): return 'hi'\n"
    )
    chunks = chunk_file(f, "mod.py")
    kinds = [c.kind for c in chunks]
    assert "module" in kinds
    # Module chunk should cover the import + constant lines.
    mod = next(c for c in chunks if c.kind == "module")
    assert "import os" in mod.text
    assert "VERSION" in mod.text


def test_python_syntax_error_falls_back_to_window(tmp_path: Path) -> None:
    f = tmp_path / "broken.py"
    f.write_text("def broken(:\n    pass\n")  # unparseable
    chunks = chunk_python(f.read_text(), "broken.py")
    # Should not raise, should yield at least one window chunk.
    assert chunks
    assert all(c.kind == "window" for c in chunks)


# --- Line-window fallback ---


def test_unknown_language_falls_back_to_window(tmp_path: Path) -> None:
    f = tmp_path / "data.txt"
    f.write_text("\n".join(f"line {i}" for i in range(300)))
    chunks = chunk_file(f, "data.txt")
    assert chunks
    assert all(c.kind == "window" for c in chunks)
    # 300 lines / step=100 (WINDOW_LINES=120, OVERLAP=20) → ≥2 windows.
    assert len(chunks) >= 2
    # Boundaries must be 1-indexed and monotonic per chunk.
    for c in chunks:
        assert 1 <= c.start_line <= c.end_line


def test_empty_file_yields_no_chunks(tmp_path: Path) -> None:
    f = tmp_path / "empty.py"
    f.write_text("")
    assert chunk_file(f, "empty.py") == []


def test_whitespace_only_file_yields_no_chunks(tmp_path: Path) -> None:
    f = tmp_path / "blank.txt"
    f.write_text("\n\n   \n")
    assert chunk_file(f, "blank.txt") == []


# --- JS/TS heuristic ---


def test_js_function_and_class_extracted(tmp_path: Path) -> None:
    f = tmp_path / "thing.ts"
    f.write_text(
        "export function add(a: number, b: number) {\n"
        "  return a + b;\n"
        "}\n"
        "\n"
        "class Greeter {\n"
        "  hello() { return 'hi'; }\n"
        "}\n"
    )
    chunks = chunk_file(f, "thing.ts")
    names = {c.name for c in chunks}
    kinds = {c.kind for c in chunks}
    assert "add" in names
    assert "Greeter" in names
    assert "function" in kinds and "class" in kinds


# --- walk_repo ---


def test_walk_skips_vendor_dirs(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "foo.js").write_text("x")
    (tmp_path / "src").mkdir()
    src = tmp_path / "src" / "main.py"
    src.write_text("print('hi')")

    paths = walk_repo(tmp_path)
    assert src in paths
    assert all(".git" not in str(p) and "node_modules" not in str(p) for p in paths)


def test_walk_skips_secrets_and_lockfiles(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET=hi")
    (tmp_path / "package-lock.json").write_text("{}")
    (tmp_path / "uv.lock").write_text("# lock")
    keep = tmp_path / "main.py"
    keep.write_text("print(1)")

    paths = walk_repo(tmp_path)
    rels = {str(p.relative_to(tmp_path)) for p in paths}
    assert "main.py" in rels
    assert ".env" not in rels
    assert "package-lock.json" not in rels
    assert "uv.lock" not in rels


def test_walk_skips_unknown_extensions(tmp_path: Path) -> None:
    (tmp_path / "weird.xyz").write_text("nope")
    keep = tmp_path / "doc.md"
    keep.write_text("# title")
    paths = walk_repo(tmp_path)
    assert keep in paths
    assert all(p.suffix != ".xyz" for p in paths)


def test_walk_skips_oversized_files(tmp_path: Path) -> None:
    big = tmp_path / "huge.txt"
    big.write_bytes(b"x" * 1_500_000)  # >1 MB
    small = tmp_path / "ok.txt"
    small.write_text("hello")
    paths = walk_repo(tmp_path)
    assert big not in paths
    assert small in paths


# --- should_skip_file ---


def test_should_skip_file_patterns() -> None:
    assert should_skip_file(".env")
    assert should_skip_file("project/.env.local")
    assert should_skip_file("creds/credentials/key.pem")
    assert should_skip_file("certs/server.pem")
    assert should_skip_file("img/logo.png")
    assert not should_skip_file("src/main.py")
    assert not should_skip_file("README.md")


# --- Chunk dataclass ---


def test_chunk_sha_stable_and_deterministic() -> None:
    c1 = Chunk(text="hello", file="a.py", start_line=1, end_line=1,
               kind="function", name="x")
    c2 = Chunk(text="hello", file="a.py", start_line=1, end_line=1,
               kind="function", name="x")
    assert c1.sha() == c2.sha()
    # Different text → different sha.
    c3 = Chunk(text="world", file="a.py", start_line=1, end_line=1,
               kind="function", name="x")
    assert c1.sha() != c3.sha()


def test_chunk_key_includes_tenant_and_repo() -> None:
    c = Chunk(text="x", file="a.py", start_line=10, end_line=20,
              kind="function", name="f")
    key = c.key(repo="myrepo", tenant_id=7)
    assert key.startswith("7:myrepo:a.py:10:")
    assert key.endswith(c.sha())
