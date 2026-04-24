"""Language-aware chunking for DevForge codebase indexing.

Day-4 scope:
  - Python via stdlib `ast` (full fidelity: functions, methods, classes, top-level).
  - TypeScript / JavaScript via heuristic regex fallback (top-level `function`,
    `class`, `export const` blocks). Upgrade to tree-sitter in a later day when
    real TS/JS repos enter the test set.
  - Everything else (markdown, yaml, toml, sql, json, txt) is chunked by
    line-windows so READMEs and config files still participate in RAG.

Each chunk carries metadata for the Vectors index:
  { tenant_id, repo, file, start_line, end_line, kind, name, sha }
"""
from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


# Files we always skip. Vendor dirs, build artifacts, lockfiles, binaries.
SKIP_DIR_NAMES = {
    ".git", ".github", ".venv", "venv", "env", "node_modules",
    "__pycache__", "dist", "build", "target", ".next", ".nuxt",
    ".cache", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    "coverage", "htmlcov",
}
# Files we always exclude by path allowlist (secrets + credentials).
# DevForge indexer refuses to touch these even if they're in the repo.
SKIP_FILE_PATTERNS = [
    re.compile(r"(^|/)\.env(\.|$)"),
    re.compile(r"(^|/)\.env\.local$"),
    re.compile(r"credentials/"),
    re.compile(r"\.pem$"),
    re.compile(r"\.key$"),
    re.compile(r"\.(png|jpg|jpeg|gif|ico|svg|pdf|zip|tar|gz|mp4|mp3|woff2?)$"),
    re.compile(r"package-lock\.json$"),
    re.compile(r"yarn\.lock$"),
    re.compile(r"pnpm-lock\.yaml$"),
    re.compile(r"uv\.lock$"),
    re.compile(r"Cargo\.lock$"),
]

# Languages we chunk with full fidelity.
PY_SUFFIXES = (".py",)
JS_TS_SUFFIXES = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")

# Anything else goes through the line-window fallback.
TEXT_SUFFIXES = (
    ".md", ".rst", ".yaml", ".yml", ".toml", ".json", ".txt",
    ".sql", ".sh", ".ini", ".cfg", ".html", ".css",
)

WINDOW_LINES = 120
WINDOW_OVERLAP = 20


@dataclass(frozen=True)
class Chunk:
    text: str
    file: str
    start_line: int
    end_line: int
    kind: str     # 'function' | 'class' | 'method' | 'module' | 'window'
    name: str     # qualified name where available, else filename

    def sha(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8", "ignore")).hexdigest()[:16]

    def key(self, repo: str, tenant_id: int) -> str:
        return f"{tenant_id}:{repo}:{self.file}:{self.start_line}:{self.sha()}"


def should_skip_file(rel_path: str) -> bool:
    for pat in SKIP_FILE_PATTERNS:
        if pat.search(rel_path):
            return True
    return False


def walk_repo(root: Path) -> list[Path]:
    """Yield all indexable file paths relative to `root`."""
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.relative_to(root).parts):
            continue
        rel = str(path.relative_to(root))
        if should_skip_file(rel):
            continue
        suf = path.suffix.lower()
        if suf not in PY_SUFFIXES + JS_TS_SUFFIXES + TEXT_SUFFIXES:
            continue
        # Size guard: skip files >1 MB (almost always generated / data files).
        if path.stat().st_size > 1_000_000:
            continue
        files.append(path)
    return files


def chunk_file(path: Path, rel_path: str) -> list[Chunk]:
    suf = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    if not text.strip():
        return []

    if suf in PY_SUFFIXES:
        return chunk_python(text, rel_path) or [_whole_file(text, rel_path, "module")]
    if suf in JS_TS_SUFFIXES:
        return chunk_js_ts(text, rel_path) or _line_windows(text, rel_path)
    return _line_windows(text, rel_path)


def _whole_file(text: str, rel_path: str, kind: str) -> Chunk:
    lines = text.count("\n") + 1
    return Chunk(text=text, file=rel_path, start_line=1, end_line=lines, kind=kind, name=rel_path)


def _line_windows(text: str, rel_path: str) -> list[Chunk]:
    lines = text.splitlines()
    if not lines:
        return []
    chunks: list[Chunk] = []
    step = max(WINDOW_LINES - WINDOW_OVERLAP, 1)
    for start in range(0, len(lines), step):
        end = min(start + WINDOW_LINES, len(lines))
        segment = "\n".join(lines[start:end])
        if not segment.strip():
            continue
        chunks.append(Chunk(
            text=segment,
            file=rel_path,
            start_line=start + 1,
            end_line=end,
            kind="window",
            name=f"{rel_path}:L{start+1}-{end}",
        ))
        if end == len(lines):
            break
    return chunks


def chunk_python(text: str, rel_path: str) -> list[Chunk]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _line_windows(text, rel_path)

    lines = text.splitlines()
    chunks: list[Chunk] = []
    module_name = Path(rel_path).stem

    # Top-level function + class blocks
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            chunks.append(_node_chunk(node, lines, rel_path, "function", node.name))
        elif isinstance(node, ast.ClassDef):
            chunks.append(_node_chunk(node, lines, rel_path, "class", node.name))
            # also emit methods individually so per-method retrieval works
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    chunks.append(_node_chunk(
                        item, lines, rel_path, "method", f"{node.name}.{item.name}"
                    ))

    # Catch-all chunk for module-level code (imports, constants, dunders).
    module_body = _module_level_code(tree, lines, rel_path, module_name)
    if module_body:
        chunks.append(module_body)

    return chunks


def _node_chunk(node, lines: list[str], rel_path: str, kind: str, name: str) -> Chunk:
    start = getattr(node, "lineno", 1)
    end = getattr(node, "end_lineno", start)
    segment = "\n".join(lines[start - 1:end])
    return Chunk(text=segment, file=rel_path, start_line=start, end_line=end, kind=kind, name=name)


def _module_level_code(tree: ast.Module, lines: list[str], rel_path: str, name: str) -> Chunk | None:
    top_lines: set[int] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", start)
        for ln in range(start, end + 1):
            top_lines.add(ln)
    if not top_lines:
        return None
    start, end = min(top_lines), max(top_lines)
    segment = "\n".join(lines[start - 1:end])
    return Chunk(text=segment, file=rel_path, start_line=start, end_line=end,
                 kind="module", name=f"{name}:module-level")


# ---------- JS / TS heuristic ----------

_JS_BLOCK_RE = re.compile(
    r"^(?P<indent>\s*)(?P<head>(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\*?|class)\s+(?P<name>[A-Za-z_$][\w$]*)[^\n]*)$",
    re.MULTILINE,
)


def chunk_js_ts(text: str, rel_path: str) -> list[Chunk]:
    """Heuristic chunker — finds top-level `function`/`class` blocks by brace matching.

    Good enough for Day 4 on a seeded repo. Tree-sitter upgrade path is clear
    and lossless when we get there.
    """
    lines = text.splitlines()
    chunks: list[Chunk] = []
    for m in _JS_BLOCK_RE.finditer(text):
        start_byte = m.start()
        # line number of the match start
        start_line = text.count("\n", 0, start_byte) + 1
        # find the opening brace after the match
        brace_idx = text.find("{", m.end())
        if brace_idx == -1:
            # arrow fn with expression body or interface decl w/o body — skip
            continue
        depth = 0
        end_idx = brace_idx
        for i in range(brace_idx, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end_idx = i
                    break
        end_line = text.count("\n", 0, end_idx) + 1
        segment = "\n".join(lines[start_line - 1:end_line])
        kind = "class" if "class " in m.group("head") else "function"
        chunks.append(Chunk(
            text=segment, file=rel_path,
            start_line=start_line, end_line=end_line,
            kind=kind, name=m.group("name"),
        ))
    return chunks
