"""Per-job git worktrees. Agents work inside these; on completion we tear them down.

We clone the tenant repo once into a cache dir (keyed by repo full name), then
create a `git worktree` for each job on a fresh feature branch.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Worktree:
    cache_repo: Path
    worktree_path: Path
    branch: str
    remote_url: str

    def cleanup(self) -> None:
        # `git worktree remove` also deletes the directory.
        subprocess.run(
            ["git", "-C", str(self.cache_repo), "worktree", "remove", "--force", str(self.worktree_path)],
            capture_output=True,
        )
        if self.worktree_path.exists():
            shutil.rmtree(self.worktree_path, ignore_errors=True)


def _cache_root() -> Path:
    root = Path(os.environ.get("DEVFORGE_DATA_DIR")
                or Path(__file__).resolve().parent.parent.parent / "data")
    return root / "worktrees"


def _run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def prepare_worktree(
    tenant_id: int,
    repo_full_name: str,
    installation_token: str,
    base_branch: str = "main",
    branch_name: str | None = None,
) -> Worktree:
    """Ensure a cache clone exists, then create a fresh worktree on `branch_name`.

    `branch_name` defaults to a timestamped devforge/<slug>-<ts> name.
    """
    cache_root = _cache_root()
    cache_root.mkdir(parents=True, exist_ok=True)
    safe = repo_full_name.replace("/", "__")
    cache = cache_root / f"{tenant_id}_{safe}"

    remote_url = f"https://x-access-token:{installation_token}@github.com/{repo_full_name}.git"

    # 1. Cache clone (create or refresh).
    if cache.exists():
        _run(["git", "remote", "set-url", "origin", remote_url], cwd=cache)
        _run(["git", "fetch", "origin", base_branch], cwd=cache, check=False)
    else:
        _run(["git", "clone", "--no-single-branch", remote_url, str(cache)])

    _run(["git", "checkout", base_branch], cwd=cache, check=False)
    _run(["git", "reset", "--hard", f"origin/{base_branch}"], cwd=cache, check=False)

    # 2. Branch name.
    if branch_name is None:
        import datetime as _dt
        ts = _dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        branch_name = f"devforge/job-{ts}"

    # 3. Worktree path (under a tempdir-style location inside data/worktrees).
    wt = cache_root / f"wt_{tenant_id}_{safe}_{branch_name.replace('/', '_')}"
    if wt.exists():
        shutil.rmtree(wt, ignore_errors=True)

    # Create a new branch tracking base_branch and add as worktree.
    _run(["git", "branch", "-f", branch_name, base_branch], cwd=cache)
    _run(["git", "worktree", "add", str(wt), branch_name], cwd=cache)

    return Worktree(
        cache_repo=cache,
        worktree_path=wt,
        branch=branch_name,
        remote_url=remote_url,
    )
