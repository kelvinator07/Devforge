import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/router";
import { useState } from "react";
import toast from "react-hot-toast";
import { ShieldCheck, Terminal } from "lucide-react";

import { mintApprovalAndRun, type PendingApproval } from "../lib/api";
import { Card } from "./ui/Card";
import { Button } from "./ui/Button";

type Props = { item: PendingApproval };

export function PendingApprovalCard({ item }: Props) {
  const { getToken } = useAuth();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleApprove() {
    if (!item.approval_command) {
      setError("No approval_command on this row (missing approval_required event).");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { job_id } = await mintApprovalAndRun(getToken, {
        command: item.approval_command,
        tenant_id: item.tenant_id,
        ticket_title: item.ticket_title,
        ticket_body: item.ticket_body,
      });
      toast.success(`Approval minted · running job #${job_id}`);
      router.push(`/jobs/${job_id}`);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      toast.error(msg);
      setBusy(false);
    }
  }

  return (
    <Card variant="accent">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-amber-400/80">#{item.id}</span>
            <span className="text-sm font-medium text-amber-100">{item.ticket_title}</span>
          </div>
          <div className="mt-1.5 line-clamp-2 text-xs text-zinc-400">{item.ticket_body}</div>
        </div>
        <Button
          variant="warning"
          size="sm"
          loading={busy}
          leftIcon={!busy ? <ShieldCheck className="h-3.5 w-3.5" /> : undefined}
          disabled={busy || !item.approval_command}
          onClick={handleApprove}
          title="Mint a token AND immediately spawn the run; navigate to its job page"
        >
          {busy ? "Starting…" : "Approve & run"}
        </Button>
      </div>
      {item.approval_command && (
        <div className="mt-3 flex items-center gap-1.5 truncate rounded-md border border-amber-500/20 bg-amber-500/5 px-2 py-1.5 font-mono text-[11px] text-amber-200/80">
          <Terminal className="h-3 w-3 shrink-0 text-amber-400/60" />
          <span className="truncate">{item.approval_command}</span>
        </div>
      )}
      {error && (
        <div className="mt-2 rounded-md border border-rose-500/40 bg-rose-500/5 px-2 py-1 text-xs text-rose-300">
          {error}
        </div>
      )}
    </Card>
  );
}
