import { SignedIn, SignedOut, RedirectToSignIn } from "@clerk/nextjs";
import Link from "next/link";
import { useState } from "react";
import {
  Plus,
  RefreshCw,
  Search,
  ExternalLink,
  Inbox,
  CheckCircle2,
  XCircle,
  Activity,
} from "lucide-react";

import { useApi, type Job, type Tenant } from "../lib/api";
import { StatusBadge } from "../components/StatusBadge";
import { NewTicketModal } from "../components/NewTicketModal";
import { Layout } from "../components/Layout";
import { Card } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { EmptyState } from "../components/ui/EmptyState";
import { Badge } from "../components/ui/Badge";

export default function Dashboard() {
  return (
    <>
      <SignedOut>
        <RedirectToSignIn />
      </SignedOut>
      <SignedIn>
        <DashboardInner />
      </SignedIn>
    </>
  );
}

type StatusFilter = "all" | "running" | "pr_opened" | "failed" | "awaiting_approval";

const FILTER_LABELS: Record<StatusFilter, string> = {
  all: "All",
  running: "Running",
  pr_opened: "PR opened",
  failed: "Failed",
  awaiting_approval: "Awaiting approval",
};

function DashboardInner() {
  const tenant = useApi<Tenant>("/tenants/me");
  const jobs = useApi<{ jobs: Job[] }>(
    tenant.data ? `/jobs?tenant_id=${tenant.data.id}&limit=50` : null,
    { pollMs: 3000 },
  );
  const [newTicketOpen, setNewTicketOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [search, setSearch] = useState("");

  const allJobs = jobs.data?.jobs ?? [];
  const totalJobs = allJobs.length;
  const success = allJobs.filter((j) => j.status === "pr_opened").length;
  const failed = allJobs.filter((j) => ["failed", "refused"].includes(j.status)).length;
  const running = allJobs.filter((j) => ["queued", "running"].includes(j.status)).length;

  const filteredJobs = allJobs.filter((j) => {
    if (statusFilter === "running" && !["queued", "running"].includes(j.status)) return false;
    if (statusFilter === "pr_opened" && j.status !== "pr_opened") return false;
    if (statusFilter === "failed" && !["failed", "refused"].includes(j.status)) return false;
    if (statusFilter === "awaiting_approval" && j.status !== "awaiting_approval") return false;
    if (search && !j.ticket_title.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <Layout width="wide">
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-[var(--text-display)] font-semibold tracking-tight text-zinc-100">
            Dashboard
          </h1>
          <p className="mt-1 text-sm text-zinc-500">
            Submit tickets, watch the crew, ship PRs.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            leftIcon={<RefreshCw className="h-3.5 w-3.5" />}
            onClick={() => {
              tenant.refresh();
              jobs.refresh();
            }}
          >
            Refresh
          </Button>
          <Button
            size="sm"
            leftIcon={<Plus className="h-3.5 w-3.5" />}
            disabled={!tenant.data}
            onClick={() => setNewTicketOpen(true)}
          >
            New ticket
          </Button>
        </div>
      </div>

      {tenant.error && (
        tenant.error.startsWith("404") ? (
          <Card variant="accent" className="mb-6">
            <div className="text-sm font-medium text-amber-200">
              No tenant linked to this account.
            </div>
            <div className="mt-1 text-xs text-zinc-400">
              Run the backfill once to link a tenant to your Clerk identity:
            </div>
            <pre className="mt-3 select-all rounded-md bg-zinc-950/60 p-3 font-mono text-[11px] text-zinc-300">
{`uv run python -m scripts.link_tenant_clerk_identity <tenant_id> --user <your_clerk_user_id>`}
            </pre>
          </Card>
        ) : (
          <ErrorCard msg={tenant.error} />
        )
      )}

      {tenant.data && (
        <Card className="mb-6" padding="md">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-xs uppercase tracking-wide text-zinc-500">Tenant</div>
              <div className="mt-0.5 text-base font-medium text-zinc-100">{tenant.data.name}</div>
              <div className="mt-1 text-xs text-zinc-400">
                owner <span className="text-zinc-200">{tenant.data.github_owner}</span>
                {" · install "}
                <span className="font-mono text-zinc-200">{tenant.data.github_installation_id}</span>
              </div>
            </div>
            <div className="flex flex-col gap-1 text-right">
              {tenant.data.repos.map((r) => (
                <div key={r.id} className="flex items-center gap-1.5 text-sm text-zinc-300">
                  <span className="font-mono">{r.full_name}</span>
                  <Badge tone="neutral">{r.default_branch}</Badge>
                </div>
              ))}
            </div>
          </div>
        </Card>
      )}

      <section className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatBox label="Total" value={totalJobs} icon={<Inbox className="h-4 w-4" />} />
        <StatBox label="Running" value={running} icon={<Activity className="h-4 w-4" />} tone="indigo" />
        <StatBox label="PR opened" value={success} icon={<CheckCircle2 className="h-4 w-4" />} tone="emerald" />
        <StatBox label="Failed" value={failed} icon={<XCircle className="h-4 w-4" />} tone="rose" />
      </section>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-[var(--text-h2)] font-semibold text-zinc-100">Recent jobs</h2>
          {(statusFilter !== "all" || search) && (
            <span className="text-xs text-zinc-500">
              {filteredJobs.length} of {totalJobs}
            </span>
          )}
        </div>

        <div className="mb-3 flex flex-wrap items-center gap-2">
          <div className="relative w-full sm:max-w-xs">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-500" />
            <Input
              placeholder="Search by title…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8"
            />
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {(["all", "running", "pr_opened", "failed", "awaiting_approval"] as const).map((s) => (
              <button
                key={s}
                onClick={() => setStatusFilter(s)}
                className={[
                  "focus-ring rounded-md border px-2.5 py-1 text-xs font-medium",
                  "transition-colors duration-[var(--dur-fast)] ease-[var(--ease)]",
                  statusFilter === s
                    ? "border-indigo-500/60 bg-indigo-500/10 text-indigo-200"
                    : "border-[var(--border)] text-zinc-400 hover:border-[var(--border-strong)] hover:text-zinc-200",
                ].join(" ")}
              >
                {FILTER_LABELS[s]}
              </button>
            ))}
          </div>
        </div>

        {jobs.loading && (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-12 rounded-md animate-shimmer" />
            ))}
          </div>
        )}
        {jobs.error && <ErrorCard msg={jobs.error} />}
        {jobs.data && filteredJobs.length === 0 && (
          <EmptyState
            icon={<Inbox className="h-5 w-5" />}
            title={statusFilter === "all" && !search ? "No jobs yet" : "No matches"}
            caption={
              statusFilter === "all" && !search
                ? "Submit your first ticket to see the crew in action."
                : "Try a different filter or search term."
            }
            action={
              statusFilter === "all" && !search ? (
                <Button
                  size="sm"
                  leftIcon={<Plus className="h-3.5 w-3.5" />}
                  onClick={() => setNewTicketOpen(true)}
                  disabled={!tenant.data}
                >
                  New ticket
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setStatusFilter("all");
                    setSearch("");
                  }}
                >
                  Clear filters
                </Button>
              )
            }
          />
        )}
        {jobs.data && filteredJobs.length > 0 && (
          <Card padding="none" className="overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-zinc-900/60 text-left text-[10px] uppercase tracking-wider text-zinc-500">
                <tr>
                  <th className="px-4 py-2.5 font-semibold">ID</th>
                  <th className="px-4 py-2.5 font-semibold">Title</th>
                  <th className="px-4 py-2.5 font-semibold">Status</th>
                  <th className="px-4 py-2.5 font-semibold">PR</th>
                  <th className="px-4 py-2.5 font-semibold">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {filteredJobs.map((j) => (
                  <tr
                    key={j.id}
                    className="transition-colors duration-[var(--dur-fast)] hover:bg-[var(--card-hover)]"
                  >
                    <td className="px-4 py-2.5 font-mono text-xs text-zinc-500">{j.id}</td>
                    <td className="px-4 py-2.5">
                      <Link
                        href={`/jobs/${j.id}`}
                        className="text-zinc-200 hover:text-indigo-300 no-underline"
                      >
                        {j.ticket_title}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5">
                      <StatusBadge status={j.status} />
                    </td>
                    <td className="px-4 py-2.5 text-xs">
                      {j.pr_url ? (
                        <a
                          href={j.pr_url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 text-emerald-400 no-underline hover:text-emerald-300"
                        >
                          Open <ExternalLink className="h-3 w-3" />
                        </a>
                      ) : (
                        <span className="text-zinc-600">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-zinc-500">
                      {formatDate(j.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </section>

      {tenant.data && (
        <NewTicketModal
          tenantId={tenant.data.id}
          open={newTicketOpen}
          onClose={() => {
            setNewTicketOpen(false);
            jobs.refresh();
          }}
        />
      )}
    </Layout>
  );
}

function formatDate(s: string): string {
  // Server sends ISO timestamps; keep relative-ish display.
  try {
    const d = new Date(s);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return s;
  }
}

function StatBox({
  label,
  value,
  icon,
  tone = "neutral",
}: {
  label: string;
  value: number;
  icon: React.ReactNode;
  tone?: "neutral" | "indigo" | "emerald" | "rose";
}) {
  const valueTint =
    tone === "emerald" ? "text-emerald-300" :
    tone === "rose" ? "text-rose-300" :
    tone === "indigo" ? "text-indigo-300" :
    "text-zinc-100";
  const iconTint =
    tone === "emerald" ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/30" :
    tone === "rose" ? "text-rose-400 bg-rose-500/10 border-rose-500/30" :
    tone === "indigo" ? "text-indigo-400 bg-indigo-500/10 border-indigo-500/30" :
    "text-zinc-400 bg-zinc-800/60 border-[var(--border)]";
  return (
    <Card variant="elevated" padding="md">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs uppercase tracking-wide text-zinc-500">{label}</div>
          <div className={`mt-1.5 text-2xl font-semibold tabular-nums ${valueTint}`}>{value}</div>
        </div>
        <div className={`flex h-8 w-8 items-center justify-center rounded-md border ${iconTint}`}>
          {icon}
        </div>
      </div>
    </Card>
  );
}

function ErrorCard({ msg }: { msg: string }) {
  return (
    <Card variant="danger" padding="sm" className="mb-4">
      <div className="text-sm text-rose-200">{msg}</div>
    </Card>
  );
}
