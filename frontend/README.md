# DevForge frontend

Next.js 16 + Clerk v6 + Tailwind v4 dashboard. The browser submits
tickets, watches the 5-agent crew run live, and approves destructive
operations — all auth'd by the user's Clerk JWT against tenant
membership (`tenants.clerk_user_id` / `clerk_org_id`). No admin secret
ever leaves the server.

## Run

```bash
cd devforge/frontend
cp .env.example .env.local             # paste Clerk keys + control-plane URL
npm install
npm run dev                            # http://localhost:3000
```

Then in another terminal start the control plane (the Makefile-driven
Docker stack handles both at once — `cd devforge && make dev`):

```bash
cd devforge && ./scripts/local_dev.sh serve   # control plane on :8001
```

Open http://localhost:3000 → sign in via Clerk → `/dashboard`.

## Pages

| Route | Purpose |
|---|---|
| `/` | Landing; redirects to `/dashboard` when signed in. |
| `/dashboard` | Tenant info + recent jobs (3s poll, status filter, search, **+ New ticket** modal). |
| `/jobs/[id]` | Live event timeline (SSE locally, polling on AWS) with skeleton placeholders before the first event lands, **view trace ↗** deep-link to LangFuse, and PR link when QA opens it. |
| `/approvals` | Pending approvals queue with **Mint + run** (one-click rerun) and copy-token fallback for CLI. |

## Layout

```
pages/                Next pages (Pages Router — static-export friendly).
  _app.tsx            ClerkProvider + react-hot-toast root.
  dashboard.tsx
  jobs/[id].tsx       Event timeline with SSE → polling fallback.
  approvals.tsx
components/
  NewTicketModal.tsx  Ticket form + 422 secret-rejection surfacing.
  PendingApprovalCard.tsx
  EventCard.tsx       One row of the timeline.
  StatusBadge.tsx
lib/
  api.ts              Typed fetch wrappers + Clerk JWT attachment.
  api.test.ts         vitest suite (9 tests).
  sse.ts              fetch-event-source wrapper for header-auth SSE.
```

## Env vars

- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` — Clerk publishable key (`pk_test_…` / `pk_live_…`).
- `CLERK_SECRET_KEY` — server-side Clerk key (used at build time for SSR auth checks; never shipped to browser).
- `NEXT_PUBLIC_DEVFORGE_API` — control plane base URL. Local: `http://localhost:8001`. AWS: API Gateway URL from `terraform/5_control_plane`.
- `NEXT_PUBLIC_LANGFUSE_PROJECT_ID` — optional. Enables the **view trace ↗** button on `/jobs/[id]`.
- `NEXT_PUBLIC_LANGFUSE_HOST` — defaults to `https://cloud.langfuse.com`.
- `NEXT_PUBLIC_DEVFORGE_USE_POLLING` — set to `1` for AWS deploys. API Gateway buffers Lambda responses, so SSE doesn't stream — the job page falls back to `GET /jobs/{id}?since_event_id=N` every 1.5s. Leave unset locally (uvicorn streams natively).

`.env.example` and `.env.production.example` document the full set.
The deploy script swaps `.env.local` aside during the production build
so the localhost API URL doesn't leak into the bundle.

## Tests

```bash
npm test               # vitest run — 9 unit tests over lib/api.ts
npm run test:watch     # watch mode
```

Covers `langfuseTraceUrl` URL building, `submitTicket` (POST + bearer
JWT + 422 secret-rejection surfacing), and `mintApprovalAndRun` (one-
click rerun forwarding). The React hook `useApi` is deferred until a
React Testing Library setup lands.

## Build + deploy

```bash
npm run build          # static export → frontend/out/
```

Production deploy goes through the repo-root script:

```bash
./scripts/deploy_aws.sh frontend   # TF apply, npm build, S3 sync, CF invalidation
```

That writes `out/` to the bucket provisioned by
`terraform/6_frontend` (S3 + CloudFront with OAC + 404→`index.html`
SPA fallback). The script auto-appends the CloudFront URL to the
control plane's CORS allowlist.

## Notes

- **Static export** (`output: "export"`) — no Next API routes, no
  middleware, no SSR. Auth lives client-side via Clerk; admin
  operations call the FastAPI control plane directly with the user's
  JWT.
- **CLI parity** — every backend endpoint accepts a Clerk JWT or an
  `X-Admin-Token` header (dual-auth). CLI tooling keeps working
  without the frontend.
- **Polling fallback on AWS** — see `NEXT_PUBLIC_DEVFORGE_USE_POLLING`
  above. The job page detects the flag and switches transport.

## Out of scope (intentionally)

- React hook tests for `useApi` — needs `@testing-library/react` +
  jsdom; bigger setup than the capstone budget.
- SSR / runtime Next host — current static-export model is sufficient
  for every feature shipped. Migrate only if a future feature
  genuinely needs server rendering.
