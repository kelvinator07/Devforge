# DevForge frontend

Next.js + Clerk + Tailwind v4 dashboard for DevForge. Watch-only in v1:
tickets are submitted via `scripts/run_ticket` from the CLI; the UI lists
tenants, tails job events live via SSE, and mints approval tokens.

## Run

```bash
cd devforge/frontend
cp .env.example .env.local             # paste Clerk keys + admin token
npm install
npm run dev                            # http://localhost:3000
```

Then in another terminal:
```bash
cd devforge && ./scripts/local_dev.sh serve   # control plane on :8001
```

Open http://localhost:3000 → sign in via Clerk → land on `/dashboard`.

## Pages

- `/` — landing; redirects to `/dashboard` when signed in.
- `/dashboard` — tenant info + recent jobs table.
- `/jobs/[id]` — live SSE-driven event timeline + PR link.
- `/approvals` — pending-approval queue with one-click admin-token mint.

## CLI parity

The CLI continues to work without the frontend. Set
`DEVFORGE_AUTH_DISABLED=1` in `devforge/.env.local` for unauthenticated CLI
dev, or add `CLERK_JWKS_URL=...` for dual-auth mode (frontend + CLI both
work).

## v1 trade-offs

- `NEXT_PUBLIC_DEVFORGE_ADMIN_TOKEN` is exposed in the browser. Demo-grade
  only. Production must move admin minting to a server-side Next.js API
  route.
- Single tenant displayed (`/tenants/1`). Schema supports multi-tenant;
  per-user scoping is a v2 wire-up.
- No ticket submission UI yet — tickets via `scripts/run_ticket` only.
- No re-run after approval from UI — copy the token to CLI to retrigger.
