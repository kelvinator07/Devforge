"""Read-only cost dashboard from the jobs + job_events tables.

Usage:
    uv run python -m backend.cost.dashboard                  # all tenants
    uv run python -m backend.cost.dashboard --tenant 1       # filter
    uv run python -m backend.cost.dashboard --json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_REPO_ROOT / ".env.local", override=False)


def main() -> None:
    tenant = None
    as_json = "--json" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--json"]
    if args and args[0] == "--tenant":
        tenant = int(args[1])

    from backend.common import get_backend
    b = get_backend()

    where = "WHERE 1=1"
    params: dict = {}
    if tenant is not None:
        where += " AND tenant_id = :t"
        params["t"] = tenant

    jobs = b.db.execute(
        f"""
        SELECT id, tenant_id, ticket_title, status, pr_url, created_at
        FROM jobs {where}
        ORDER BY id DESC
        LIMIT 50
        """,
        params,
    )

    # Extract cost events from job_events (we write a `cost_summary` event at job_done).
    rows = []
    for j in jobs:
        costs = b.db.execute(
            "SELECT payload FROM job_events WHERE job_id=:j AND event='cost_summary' ORDER BY id DESC LIMIT 1",
            {"j": j["id"]},
        )
        total = 0.0
        by_model: dict[str, float] = {}
        if costs:
            try:
                pl = json.loads(costs[0]["payload"])
                total = float(pl.get("spent_usd", 0.0))
                by_model = pl.get("by_model", {}) or {}
            except Exception:
                pass
        rows.append({
            "job_id": j["id"],
            "tenant_id": j["tenant_id"],
            "status": j["status"],
            "title": (j["ticket_title"] or "")[:50],
            "total_usd": total,
            "by_model": by_model,
            "pr": j.get("pr_url") or "",
        })

    if as_json:
        print(json.dumps({"jobs": rows}, indent=2))
        return

    grand_total = sum(r["total_usd"] for r in rows)
    print(f"{'job':>5}  {'tenant':>6}  {'status':18s}  {'cost':>8}  title")
    print("-" * 100)
    for r in rows:
        print(f"{r['job_id']:>5}  {r['tenant_id']:>6}  {r['status']:18s}  ${r['total_usd']:>7.4f}  {r['title']}")
        for m, c in r["by_model"].items():
            print(f"{'':>36s}    {m:30s}  ${c:.4f}")
    print("-" * 100)
    print(f"TOTAL: ${grand_total:.4f} across {len(rows)} jobs")


if __name__ == "__main__":
    main()
