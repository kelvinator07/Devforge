"""Link an existing tenant to a Clerk identity so the dashboard can resolve
it via GET /tenants/me (B1, multi-tenant scoping).

Usage:
    uv run python -m scripts.link_tenant_clerk_identity <tenant_id> --user user_…
    uv run python -m scripts.link_tenant_clerk_identity <tenant_id> --org  org_…
    uv run python -m scripts.link_tenant_clerk_identity <tenant_id> --user user_… --org org_…

At least one of --user / --org is required. Existing values are NOT overwritten
unless --force is passed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env.local", override=False)
load_dotenv(_REPO_ROOT / ".env", override=False)

from backend.common import get_backend  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Link a tenant to a Clerk identity.")
    p.add_argument("tenant_id", type=int)
    p.add_argument("--user", dest="user_id", help="Clerk user_id (e.g. user_2abc…)")
    p.add_argument("--org", dest="org_id", help="Clerk org_id (e.g. org_2def…)")
    p.add_argument("--force", action="store_true",
                   help="overwrite existing values (default: only set when null)")
    args = p.parse_args()

    if not args.user_id and not args.org_id:
        p.error("at least one of --user or --org is required")

    db = get_backend().db
    rows = db.execute(
        "SELECT id, name, clerk_user_id, clerk_org_id FROM tenants WHERE id = :t",
        {"t": args.tenant_id},
    )
    if not rows:
        print(f"tenant {args.tenant_id} not found", file=sys.stderr)
        return 1
    t = rows[0]
    print(f"tenant {t['id']} ({t['name']!r}): "
          f"clerk_user_id={t['clerk_user_id']!r}, clerk_org_id={t['clerk_org_id']!r}")

    if args.force:
        db.execute(
            "UPDATE tenants SET clerk_user_id=:u, clerk_org_id=:o WHERE id=:t",
            {"u": args.user_id, "o": args.org_id, "t": args.tenant_id},
        )
    else:
        db.execute(
            """
            UPDATE tenants
            SET clerk_user_id = COALESCE(clerk_user_id, :u),
                clerk_org_id  = COALESCE(clerk_org_id,  :o)
            WHERE id = :t
            """,
            {"u": args.user_id, "o": args.org_id, "t": args.tenant_id},
        )

    after = db.execute(
        "SELECT clerk_user_id, clerk_org_id FROM tenants WHERE id = :t",
        {"t": args.tenant_id},
    )[0]
    print(f"after: clerk_user_id={after['clerk_user_id']!r}, clerk_org_id={after['clerk_org_id']!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
