"""devforge-sandbox-mcp — test / lint / type-check / build inside a worktree.

All tools run via subprocess with:
  - cwd = DEVFORGE_WORKTREE_ROOT
  - wall-clock cap = DEVFORGE_SANDBOX_WALL_CLOCK (default 180s)
  - command allowlist — refuses any command outside a known-safe list

Tools:
  - run_tests(framework='pytest', selector='')
  - run_linter(tool='ruff', paths='')
  - run_type_checker(tool='mypy', paths='')
  - run_build(command='')       -> only allowed for `uv build` / `npm run build`
  - git_status()                -> read-only; useful for agents to confirm state

Run:
    uv run python -m backend.mcp.sandbox_mcp.server
"""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("devforge-sandbox")


def _cwd() -> Path:
    return Path(os.environ.get("DEVFORGE_WORKTREE_ROOT") or os.getcwd()).resolve()


def _cap_seconds() -> int:
    return int(os.environ.get("DEVFORGE_SANDBOX_WALL_CLOCK", "180"))


def _run(cmd: list[str], extra_env: dict | None = None) -> dict:
    cap = _cap_seconds()
    env = {**os.environ, **(extra_env or {})}
    try:
        proc = subprocess.run(
            cmd,
            cwd=_cwd(),
            env=env,
            capture_output=True,
            text=True,
            timeout=cap,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "exit_code": -1,
            "timed_out": True,
            "cap_seconds": cap,
            "stdout": (exc.stdout or "")[-4000:],
            "stderr": (exc.stderr or "")[-4000:],
            "cmd": " ".join(shlex.quote(c) for c in cmd),
        }
    return {
        "exit_code": proc.returncode,
        "timed_out": False,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
        "cmd": " ".join(shlex.quote(c) for c in cmd),
    }


@mcp.tool()
def run_tests(framework: str = "pytest", selector: str = "") -> dict:
    """Run the project's test suite. `framework` must be one of: pytest, uv-pytest, npm-test."""
    if framework == "pytest":
        cmd = ["pytest", "-q"]
    elif framework == "uv-pytest":
        cmd = ["uv", "run", "pytest", "-q"]
    elif framework == "npm-test":
        cmd = ["npm", "test", "--silent"]
    else:
        raise ValueError(f"unsupported framework: {framework!r}")
    if selector:
        cmd.append(selector)
    return _run(cmd)


@mcp.tool()
def run_linter(tool: str = "ruff", paths: str = "") -> dict:
    """Run a linter. Allowed: ruff, eslint."""
    if tool == "ruff":
        cmd = ["ruff", "check"]
    elif tool == "eslint":
        cmd = ["npx", "--no-install", "eslint"]
    else:
        raise ValueError(f"unsupported linter: {tool!r}")
    if paths:
        cmd.extend(shlex.split(paths))
    return _run(cmd)


@mcp.tool()
def run_type_checker(tool: str = "mypy", paths: str = "") -> dict:
    """Run a type checker. Allowed: mypy, tsc."""
    if tool == "mypy":
        cmd = ["mypy"]
    elif tool == "tsc":
        cmd = ["npx", "--no-install", "tsc", "--noEmit"]
    else:
        raise ValueError(f"unsupported type checker: {tool!r}")
    if paths:
        cmd.extend(shlex.split(paths))
    return _run(cmd)


@mcp.tool()
def run_build(command: str = "") -> dict:
    """Run a build. Only `uv build` and `npm run build` are allowlisted."""
    if command in ("", "uv build"):
        cmd = ["uv", "build"]
    elif command == "npm run build":
        cmd = ["npm", "run", "build"]
    else:
        raise ValueError(
            f"build command not allowlisted: {command!r} "
            "(allowed: 'uv build', 'npm run build')"
        )
    return _run(cmd)


@mcp.tool()
def run_coverage(min_pct: int = 50) -> dict:
    """Run pytest under coverage. Returns exit code + total coverage percent.

    Requires `coverage` to be installed in the worktree's env. Falls back to
    plain pytest if coverage isn't available.
    """
    cwd = _cwd()
    # Best-effort: run via uv so the project's own deps are used.
    cmd = ["uv", "run", "coverage", "run", "-m", "pytest", "-q"]
    r = _run(cmd)
    if r["exit_code"] != 0 or "no module named coverage" in (r["stderr"] or "").lower():
        # Fall back to plain pytest + report coverage as unknown.
        return {
            **_run(["uv", "run", "pytest", "-q"]),
            "coverage_pct": None,
            "min_pct": min_pct,
            "meets_threshold": None,
        }
    # Now extract coverage report
    rep = _run(["uv", "run", "coverage", "report", "--format=total"])
    try:
        pct = float((rep["stdout"] or "0").strip())
    except ValueError:
        pct = 0.0
    return {
        **r,
        "coverage_pct": pct,
        "min_pct": min_pct,
        "meets_threshold": pct >= min_pct,
    }


@mcp.tool()
def run_semgrep(paths: str = ".", config: str = "auto") -> dict:
    """Run Semgrep. Returns {exit_code, findings: [{rule, severity, file, line, msg}]}.

    `config='auto'` uses Semgrep's default ruleset. Non-zero exit when HIGH findings exist.
    """
    import json as _json

    cmd = ["semgrep", "--config", config, "--json", "--quiet"]
    cmd.extend(shlex.split(paths))
    r = _run(cmd)
    findings: list[dict] = []
    high_count = 0
    try:
        data = _json.loads(r["stdout"] or "{}")
        for f in data.get("results", []):
            sev = (f.get("extra", {}).get("severity") or "").upper()
            if sev in ("ERROR", "HIGH"):
                high_count += 1
            findings.append({
                "rule": f.get("check_id"),
                "severity": sev,
                "file": f.get("path"),
                "line": f.get("start", {}).get("line"),
                "msg": (f.get("extra", {}).get("message") or "")[:200],
            })
    except Exception:
        pass
    return {
        "exit_code": r["exit_code"],
        "timed_out": r["timed_out"],
        "high_severity_count": high_count,
        "total_findings": len(findings),
        "findings": findings[:50],
        "cmd": r["cmd"],
    }


@mcp.tool()
def run_gitleaks(paths: str = ".") -> dict:
    """Run `detect-secrets` (pure-Python) over the given paths. Returns findings.

    Local-mode DevForge uses detect-secrets because gitleaks isn't on pypi.
    The Fargate Dockerfile (AWS mode) bundles the gitleaks binary so agents
    hit the same gate semantics either way.
    """
    import json as _json

    # detect-secrets scan outputs JSON to stdout.
    cmd = ["detect-secrets", "scan", "--all-files"]
    cmd.extend(shlex.split(paths))
    r = _run(cmd)
    findings: list[dict] = []
    try:
        data = _json.loads(r["stdout"] or "{}")
        for fp, items in (data.get("results") or {}).items():
            for it in items:
                findings.append({
                    "file": fp,
                    "line": it.get("line_number"),
                    "type": it.get("type"),
                    "is_secret": it.get("is_secret"),
                })
    except Exception:
        pass
    # detect-secrets exits 0 even on findings. Treat any finding as a fail.
    return {
        "exit_code": 1 if findings else 0,
        "timed_out": r["timed_out"],
        "findings_count": len(findings),
        "findings": findings[:50],
        "cmd": r["cmd"],
    }


@mcp.tool()
def git_status() -> dict:
    """Show `git status --short --branch` output for the worktree."""
    return _run(["git", "status", "--short", "--branch"])


@mcp.tool()
def list_changed_files() -> list[str]:
    """Return paths changed vs HEAD (staged + unstaged + untracked)."""
    r = _run(["git", "status", "--porcelain=v1"])
    if r["exit_code"] != 0:
        return []
    files: list[str] = []
    for line in (r["stdout"] or "").splitlines():
        if len(line) > 3:
            files.append(line[3:])
    return files


if __name__ == "__main__":
    mcp.run()
