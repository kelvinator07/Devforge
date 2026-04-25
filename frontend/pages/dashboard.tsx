import { SignedIn, SignedOut, RedirectToSignIn, UserButton } from "@clerk/nextjs";
import Link from "next/link";
import { useState } from "react";

import { useApi, type Job, type Tenant } from "../lib/api";
import { StatusBadge } from "../components/StatusBadge";
import { NewTicketModal } from "../components/NewTicketModal";

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

function DashboardInner() {
  const tenant = useApi<Tenant>("/tenants/1");
  const jobs = useApi<{ jobs: Job[] }>("/jobs?tenant_id=1&limit=50", { pollMs: 3000 });
  const [newTicketOpen, setNewTicketOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [search, setSearch] = useState("");

  const allJobs = jobs.data?.jobs ?? [];
  const totalJobs = allJobs.length;
  const success = allJobs.filter((j) => j.status === "pr_opened").length;
  const failed = allJobs.filter((j) => ["failed", "refused"].includes(j.status)).length;

  const filteredJobs = allJobs.filter((j) => {
    if (statusFilter === "running" && !["queued", "running"].includes(j.status)) return false;
    if (statusFilter === "pr_opened" && j.status !== "pr_opened") return false;
    if (statusFilter === "failed" && !["failed", "refused"].includes(j.status)) return false;
    if (statusFilter === "awaiting_approval" && j.status !== "awaiting_approval") return false;
    if (search && !j.ticket_title.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <header className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">DevForge</h1>
          <p className="text-sm text-zinc-500">
            <Link href="/dashboard">Dashboard</Link>
            {" · "}
            <Link href="/approvals">Approvals</Link>
          </p>
        </div>
        <UserButton />
      </header>

      {tenant.error && <ErrorCard msg={tenant.error} />}
      {tenant.data && (
        <section className="mb-8 rounded border border-zinc-800 bg-[var(--card)] p-4">
          <div className="text-xs uppercase tracking-wide text-zinc-500">tenant</div>
          <div className="mt-1 text-lg font-medium">{tenant.data.name}</div>
          <div className="mt-1 text-sm text-zinc-400">
            owner: <span className="text-zinc-200">{tenant.data.github_owner}</span>
            {" · install: "}
            <span className="text-zinc-200">{tenant.data.github_installation_id}</span>
          </div>
          <div className="mt-3">
            {tenant.data.repos.map((r) => (
              <div key={r.id} className="text-sm text-zinc-300">
                {r.full_name}
                <span className="ml-2 text-xs text-zinc-500">({r.default_branch})</span>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="mb-6 grid grid-cols-3 gap-4">
        <StatBox label="jobs" value={totalJobs} />
        <StatBox label="pr_opened" value={success} accent="emerald" />
        <StatBox label="failed/refused" value={failed} accent="rose" />
      </section>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-medium">Recent jobs</h2>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setNewTicketOpen(true)}
              disabled={!tenant.data}
              className="rounded bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
            >
              + New ticket
            </button>
            <button
              onClick={() => { tenant.refresh(); jobs.refresh(); }}
              className="text-xs text-zinc-400 hover:text-zinc-200"
            >
              Refresh
            </button>
          </div>
        </div>

        <div className="mb-3 flex flex-wrap items-center gap-2">
          <input
            type="text"
            placeholder="search title…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="rounded border border-zinc-700 bg-zinc-900 px-3 py-1 text-xs text-zinc-100 outline-none focus:border-indigo-500"
          />
          {(["all", "running", "pr_opened", "failed", "awaiting_approval"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`rounded border px-2.5 py-1 text-xs ${
                statusFilter === s
                  ? "border-indigo-500 bg-indigo-500/10 text-indigo-200"
                  : "border-zinc-700 text-zinc-400 hover:bg-zinc-800"
              }`}
            >
              {s}
            </button>
          ))}
          {(statusFilter !== "all" || search) && (
            <span className="ml-auto text-xs text-zinc-500">
              {filteredJobs.length} of {totalJobs}
            </span>
          )}
        </div>
        {jobs.loading && <div className="text-zinc-500">loading...</div>}
        {jobs.error && <ErrorCard msg={jobs.error} />}
        {jobs.data && (
          <div className="overflow-hidden rounded border border-zinc-800">
            <table className="w-full text-sm">
              <thead className="bg-zinc-900 text-left text-xs uppercase tracking-wide text-zinc-500">
                <tr>
                  <th className="px-4 py-2 font-medium">id</th>
                  <th className="px-4 py-2 font-medium">title</th>
                  <th className="px-4 py-2 font-medium">status</th>
                  <th className="px-4 py-2 font-medium">PR</th>
                  <th className="px-4 py-2 font-medium">created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800">
                {filteredJobs.length === 0 && (
                  <tr><td colSpan={5} className="px-4 py-6 text-center text-xs text-zinc-500">no jobs match this filter</td></tr>
                )}
                {filteredJobs.map((j) => (
                  <tr key={j.id} className="hover:bg-zinc-900/50">
                    <td className="px-4 py-2 font-mono text-zinc-400">{j.id}</td>
                    <td className="px-4 py-2">
                      <Link href={`/jobs/${j.id}`} className="text-indigo-300 hover:underline">
                        {j.ticket_title}
                      </Link>
                    </td>
                    <td className="px-4 py-2"><StatusBadge status={j.status} /></td>
                    <td className="px-4 py-2 text-xs">
                      {j.pr_url ? (
                        <a href={j.pr_url} target="_blank" rel="noreferrer" className="text-emerald-400">
                          open ↗
                        </a>
                      ) : (
                        <span className="text-zinc-600">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-xs text-zinc-500">{j.created_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {tenant.data && (
        <NewTicketModal
          tenantId={tenant.data.id}
          open={newTicketOpen}
          onClose={() => { setNewTicketOpen(false); jobs.refresh(); }}
        />
      )}
    </div>
  );
}

function StatBox({ label, value, accent }: { label: string; value: number; accent?: string }) {
  const tint =
    accent === "emerald" ? "text-emerald-300" :
    accent === "rose"    ? "text-rose-300" :
    "text-zinc-100";
  return (
    <div className="rounded border border-zinc-800 bg-[var(--card)] p-4">
      <div className="text-xs uppercase tracking-wide text-zinc-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${tint}`}>{value}</div>
    </div>
  );
}

function ErrorCard({ msg }: { msg: string }) {
  return (
    <div className="rounded border border-rose-700/40 bg-rose-500/5 p-3 text-sm text-rose-300">
      {msg}
    </div>
  );
}
