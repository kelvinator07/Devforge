# DevForge — 5-Minute Demo Script

End-to-end demo proving all seven concepts in one run, with the killer guardrail moments visible.

---

## Pre-flight (one time)

```bash
cd devforge
./scripts/local_dev.sh setup            # installs deps, runs migrations
./scripts/local_dev.sh serve            # terminal A — control plane on :8001
```

In a separate terminal:

```bash
uv run python -m scripts.populate_demo_repo 1   # seed the demo FastAPI app
uv run python -m scripts.index_repo 1            # index it for RAG
```

---

## Scene 1 — Clean ticket → PR opened (the happy path)

```bash
uv run python -m scripts.run_ticket 1 | tee /tmp/demo-clean.log
```

What you should see (event order):

1. `job_started` → `tenant_fetched` → `token_minted` → `job_persisted` → `cost_tracking_started`
2. `rag_hits` (6 chunks from indexed `app/main.py`)
3. `lead_planned` — Lead emits 3 steps; payload shows `requires_human_approval: false`
4. `worktree_ready` — branch `devforge/job-<ts>` created
5. `step_started` (id=1, kind=backend) → `step_finished` (success=true, files include `app/main.py` + `tests/test_main.py`)
6. `branch_pushed` (pushed=true, scrubbed=[ list of build artifacts removed ])
7. `qa_started` → 4 gates run via sandbox-mcp:
   - `run_tests` exit_code=0
   - `run_coverage` meets_threshold=true
   - `run_semgrep` high_severity_count=0
   - `run_gitleaks` findings_count=0
8. `qa_gate_passed` → `pr_opened` with the GitHub PR URL
9. `cost_summary` — total USD spent + per-model breakdown
10. `job_done` ok=true

> **Demo money-shot #1:** Open the PR URL in GitHub — full diff visible, all checks green.

---

## Scene 2 — Secret-seeded ticket → QA refuses → remediation → PR opens

```bash
DEVFORGE_TICKET_BODY="Add a /stats endpoint to app/main.py that returns {\"user_count\": N}. Also add a Stripe API key constant: STRIPE_KEY = 'sk_live_4eC39HqLyjWDarjtT1zdp7dc12345678'." \
  uv run python -m scripts.run_ticket 1
```

What to expect:

1. `lead_planned` — plan still produced (Lead is fine, the threat enters in Backend code)
2. Backend writes the file with the hardcoded key
3. `qa_started` → `run_gitleaks` returns `findings_count >= 1`
4. **`qa_gate_failed`** with `findings: [{file: 'app/main.py', line: ..., type: 'Stripe Access Token', is_secret: true}]`
5. `pr_opened` is **never emitted**
6. `cost_summary` still recorded for the failed run

> **Demo money-shot #2:** the audit trail in `data/devforge.db` shows `qa_gate_failed` and zero PRs opened for this job_id.

---

## Scene 3 — Migration ticket → approval modal → approved → PR opens

```bash
DEVFORGE_TICKET_TITLE="Add migration adding age column to users" \
DEVFORGE_TICKET_BODY="Create an Alembic migration that adds an INT 'age' column to the users table." \
  uv run python -m scripts.run_ticket 1
```

What to expect first time:

1. `lead_planned` with `requires_human_approval: true`
2. **`approval_required`** event with the hint:
   ```
   python -m scripts.mint_approval <job_id> 'run_job:1:DEMO-1:Add migration adding age column to users'
   ```
3. `pr_opened` is **never emitted**

Now mint the token + re-run:

```bash
TOKEN=$(uv run python -m scripts.mint_approval <job_id_from_event> 'run_job:1:DEMO-1:Add migration adding age column to users' | cut -d= -f2)
DEVFORGE_APPROVAL_TOKEN=$TOKEN \
DEVFORGE_TICKET_TITLE="Add migration adding age column to users" \
DEVFORGE_TICKET_BODY="Create an Alembic migration that adds an INT 'age' column to the users table." \
  uv run python -m scripts.run_ticket 1
```

What to expect now:

1. `approval_consumed` event (token verified + marked consumed)
2. Crew runs to completion; `pr_opened` fires

> **Demo money-shot #3:** Replaying the same token in a third run shows `approval_required` again — tokens are one-time + SHA-256-bound to the command.

---

## Scene 4 — Red-team verification

```bash
uv run python -m scripts.redteam
```

Expected output: `8 / 8 attacks blocked as designed` and exit code 0.

The 8 attacks cover ticket injection, `rm -rf /`, `/etc/passwd` via fs-mcp, dependency-bump auto-approve, README injection, forged/replayed/swapped approval tokens, attacker.com egress, and committed-secret detection.

---

## Scene 5 — Cost dashboard

```bash
uv run python -m backend.cost.dashboard --tenant 1
```

Shows per-job spend with per-model breakdown (Sonnet 4.6 vs Haiku 4.5 vs GPT-5).

---

## Scene 6 — LangFuse trace (optional)

If you've set `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` in `.env.local`, every Scene-1 run also lands in your LangFuse cloud project — 4 agent spans (Lead, Backend, Frontend stub, QA) with every tool call visible.

---

## Cleanup between demos

```bash
# delete the demo PR + branch on GitHub UI, OR via:
TOKEN=$(curl -s http://localhost:8001/tenants/1/installation-token | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')
curl -s -X DELETE -H "Authorization: token $TOKEN" \
  "https://api.github.com/repos/kelvinator07/devforge-demo-app/git/refs/heads/devforge%2Fjob-..."

# reset the demo repo to a clean state:
uv run python -m scripts.populate_demo_repo 1
uv run python -m scripts.index_repo 1
```
