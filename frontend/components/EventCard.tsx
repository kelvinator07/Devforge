import { useState } from "react";

type Props = {
  id: number;
  type: string;
  data: Record<string, unknown>;
  ts?: string;
};

const ACCENT: Record<string, string> = {
  pr_opened: "border-l-emerald-500",
  qa_gate_passed: "border-l-emerald-500",
  branch_pushed: "border-l-emerald-500",
  approval_consumed: "border-l-emerald-500",
  prior_approvals_superseded: "border-l-zinc-500",

  qa_gate_failed: "border-l-rose-500",
  approval_required: "border-l-amber-500",
  injection_detected: "border-l-amber-500",
  branch_push_failed: "border-l-rose-500",

  lead_planned: "border-l-indigo-500",
  rag_hits: "border-l-indigo-500",
  step_started: "border-l-blue-500",
  step_finished: "border-l-blue-500",
  migration_staged: "border-l-purple-500",

  cost_summary: "border-l-cyan-500",
  job_started: "border-l-zinc-500",
  job_done: "border-l-zinc-500",
};

export function EventCard({ id, type, data, ts }: Props) {
  const [open, setOpen] = useState(false);
  const accent = ACCENT[type] || "border-l-zinc-600";
  const summary = friendlySummary(type, data);
  return (
    <div className={`rounded border border-zinc-800 border-l-4 ${accent} bg-[var(--card)] p-3`}>
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-wide text-zinc-500">#{id} · {type}</div>
          <div className="mt-0.5 text-sm text-zinc-200">{summary}</div>
        </div>
        <button
          className="shrink-0 text-xs text-zinc-400 hover:text-zinc-200"
          onClick={() => setOpen((o) => !o)}
        >
          {open ? "hide" : "details"}
        </button>
      </div>
      {ts && <div className="mt-1 text-[10px] text-zinc-500">{ts}</div>}
      {open && (
        <pre className="mt-2 max-h-64 overflow-auto text-xs text-zinc-300">
{JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  );
}

function friendlySummary(type: string, d: Record<string, unknown>): string {
  switch (type) {
    case "job_started":      return `tenant ${d.tenant_id ?? "?"} · ${d.ticket_id ?? ""} · ${d.ticket_title ?? ""}`;
    case "tenant_fetched":   return `repo: ${d.repo ?? ""}`;
    case "rag_hits":         return `${d.count ?? "?"} chunks retrieved`;
    case "lead_planned":     return `${(d.steps as unknown[] | undefined)?.length ?? "?"} steps · est $${(d.estimated_cost_usd as number | undefined)?.toFixed?.(2) ?? "?"}`;
    case "step_started":     return `step ${d.id} (${d.kind})`;
    case "step_finished":    return `step ${d.id} · ${d.success ? "OK" : "FAIL"}`;
    case "qa_gate_passed":   return `${d.findings ?? 0} findings`;
    case "qa_gate_failed":   return `${d.count ?? "?"} findings · ${d.reason ?? ""}`;
    case "branch_pushed":    return `${d.branch ?? ""} ${d.pushed ? "pushed" : "(not pushed)"}`;
    case "pr_opened":        return String(d.url ?? "");
    case "migration_staged": return `${(d.files as string[] | undefined)?.join(", ") ?? ""}`;
    case "approval_required":return `${d.approval_command ?? ""}`;
    case "approval_consumed":return `job ${d.job_id ?? ""}`;
    case "prior_approvals_superseded": {
      const ids = (d.superseded_job_ids as number[] | undefined) ?? [];
      return `superseded ${ids.length} prior job${ids.length === 1 ? "" : "s"}: ${ids.join(", ")}`;
    }
    case "cost_summary":     return `$${(d.spent_usd as number | undefined)?.toFixed?.(4) ?? "?"} · ${d.calls ?? "?"} calls`;
    case "job_done":         return d.ok ? `OK · ${d.pr_url ?? ""}` : `FAIL · ${d.reason ?? ""}`;
    default:                 return "";
  }
}
