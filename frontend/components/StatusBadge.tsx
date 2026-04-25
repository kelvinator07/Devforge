type Props = { status: string };

const COLORS: Record<string, string> = {
  pr_opened: "bg-emerald-500/15 text-emerald-300 border-emerald-700/40",
  running: "bg-blue-500/15 text-blue-300 border-blue-700/40",
  queued: "bg-zinc-500/15 text-zinc-300 border-zinc-700/40",
  failed: "bg-rose-500/15 text-rose-300 border-rose-700/40",
  refused: "bg-rose-500/15 text-rose-300 border-rose-700/40",
  awaiting_approval: "bg-amber-500/15 text-amber-300 border-amber-700/40",
};

export function StatusBadge({ status }: Props) {
  const cls = COLORS[status] || "bg-zinc-500/15 text-zinc-300 border-zinc-700/40";
  return (
    <span className={`inline-block rounded border px-2 py-0.5 text-xs font-medium ${cls}`}>
      {status}
    </span>
  );
}
