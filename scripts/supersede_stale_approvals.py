"""One-shot backfill: mark stale `awaiting_approval` jobs as `approval_superseded`.

Why this exists: the orchestrator now sweeps prior `awaiting_approval` rows
on every `approval_consumed`, but rows from before that change still sit on
`/approvals/pending` forever. Run this once to clean them up.

Heuristic (matches what the orchestrator does at runtime, but reconstructed
without relying on the consumer's own `approval_required` event — the
consumer doesn't emit one because it has a valid token):

  A job is considered superseded if there's a *later* job in the same
  tenant with the same ticket_title that escaped `awaiting_approval`
  (status anything except 'awaiting_approval'). Equal tenant + equal
  ticket_title implies equal `approval_command` for the default ticket_id
  ("DEMO-1") used by `scripts.run_ticket`.

Usage:
    uv run python -m scripts.supersede_stale_approvals --dry-run
    uv run python -m scripts.supersede_stale_approvals
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env.local", override=False)
load_dotenv(_REPO_ROOT / ".env", override=False)

from backend.common import get_backend  # noqa: E402


def main(dry_run: bool) -> int:
    db = get_backend().db
    awaiting = db.execute(
        "SELECT id, tenant_id, ticket_title FROM jobs "
        "WHERE status = 'awaiting_approval' ORDER BY id"
    )
    if not awaiting:
        print("no awaiting_approval rows found — nothing to do.")
        return 0

    superseded = 0
    for j in awaiting:
        job_id, tenant_id, title = j["id"], j["tenant_id"], j["ticket_title"]
        later = db.execute(
            "SELECT id, status FROM jobs "
            "WHERE tenant_id = :t AND ticket_title = :title "
            "AND id > :j AND status != 'awaiting_approval' "
            "ORDER BY id LIMIT 1",
            {"t": tenant_id, "title": title, "j": job_id},
        )
        if not later:
            print(f"  job {job_id}: still genuinely pending ({title!r})")
            continue
        successor = later[0]
        verb = "would supersede" if dry_run else "superseded"
        print(f"{verb} job {job_id} (succeeded by job {successor['id']} status={successor['status']!r}): {title!r}")
        if not dry_run:
            db.execute(
                "UPDATE jobs SET status='approval_superseded' WHERE id=:j",
                {"j": job_id},
            )
        superseded += 1

    prefix = "(dry-run) " if dry_run else ""
    print(f"\n{prefix}superseded {superseded} of {len(awaiting)} awaiting_approval rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv))
