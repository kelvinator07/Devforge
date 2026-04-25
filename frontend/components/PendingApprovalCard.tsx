import { useRouter } from "next/router";
import { useState } from "react";
import toast from "react-hot-toast";

import { mintApprovalAndRun, type PendingApproval } from "../lib/api";

type Props = { item: PendingApproval };

export function PendingApprovalCard({ item }: Props) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleApprove() {
    if (!item.approval_command) {
      setError("no approval_command on this row (missing approval_required event)");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { job_id } = await mintApprovalAndRun({
        command: item.approval_command,
        tenant_id: item.tenant_id,
        ticket_title: item.ticket_title,
        ticket_body: item.ticket_body,
      });
      toast.success(`approval minted · running job #${job_id}`);
      router.push(`/jobs/${job_id}`);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      toast.error(msg);
      setBusy(false);
    }
  }

  return (
    <div className="rounded border border-amber-700/40 bg-amber-500/5 p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-medium text-amber-200">job #{item.id} · {item.ticket_title}</div>
          <div className="mt-1 truncate text-xs text-zinc-500">{item.ticket_body}</div>
        </div>
        <button
          disabled={busy || !item.approval_command}
          onClick={handleApprove}
          className="shrink-0 rounded bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-500 disabled:opacity-50"
          title="Mint a token AND immediately spawn the run; navigate to its job page"
        >
          {busy ? "starting..." : "Approve & run"}
        </button>
      </div>
      {item.approval_command && (
        <div className="mt-2 truncate font-mono text-[11px] text-zinc-500">
          {item.approval_command}
        </div>
      )}
      {error && <div className="mt-2 text-xs text-rose-400">{error}</div>}
    </div>
  );
}
