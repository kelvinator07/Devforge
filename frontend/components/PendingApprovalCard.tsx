import { useState } from "react";

import { mintApproval, type PendingApproval } from "../lib/api";

type Props = { item: PendingApproval };

export function PendingApprovalCard({ item }: Props) {
  const [token, setToken] = useState<string | null>(null);
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
      const { token } = await mintApproval(item.approval_command);
      setToken(token);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
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
        {!token && (
          <button
            disabled={busy || !item.approval_command}
            onClick={handleApprove}
            className="shrink-0 rounded bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-500 disabled:opacity-50"
          >
            {busy ? "minting..." : "Approve"}
          </button>
        )}
      </div>
      {item.approval_command && (
        <div className="mt-2 truncate font-mono text-[11px] text-zinc-500">
          {item.approval_command}
        </div>
      )}
      {error && <div className="mt-2 text-xs text-rose-400">{error}</div>}
      {token && (
        <div className="mt-3 rounded bg-zinc-900 p-3 text-xs">
          <div className="mb-1 text-emerald-400">approval token minted (5-min TTL)</div>
          <div className="break-all font-mono text-zinc-200">{token}</div>
          <div className="mt-2 text-zinc-500">
            Re-run from CLI:
            <pre className="mt-1 select-all">
{`DEVFORGE_APPROVAL_TOKEN=${token} \\
DEVFORGE_TICKET_TITLE=${JSON.stringify(item.ticket_title)} \\
DEVFORGE_TICKET_BODY=${JSON.stringify(item.ticket_body)} \\
  uv run python -m scripts.run_ticket ${item.tenant_id}`}
            </pre>
          </div>
          <button
            onClick={() => navigator.clipboard.writeText(token)}
            className="mt-2 rounded border border-zinc-700 px-2 py-1 text-zinc-300 hover:bg-zinc-800"
          >
            copy token
          </button>
        </div>
      )}
    </div>
  );
}
