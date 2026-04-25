import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/router";
import { useState } from "react";
import toast from "react-hot-toast";

import { submitTicket } from "../lib/api";

type Props = {
  tenantId: number;
  open: boolean;
  onClose: () => void;
};

export function NewTicketModal({ tenantId, open, onClose }: Props) {
  const { getToken } = useAuth();
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !body.trim()) {
      setError("title and body are required");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { job_id } = await submitTicket(getToken, {
        tenant_id: tenantId,
        ticket_title: title.trim(),
        ticket_body: body.trim(),
      });
      toast.success(`ticket submitted · job #${job_id}`);
      onClose();
      router.push(`/jobs/${job_id}`);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      toast.error(msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={onClose}
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
        className="w-full max-w-2xl rounded border border-zinc-800 bg-[var(--card)] p-6 shadow-xl"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-medium">New ticket</h2>
          <button type="button" onClick={onClose} className="text-sm text-zinc-500 hover:text-zinc-300">
            close
          </button>
        </div>

        <label className="block text-xs uppercase tracking-wide text-zinc-500">title</label>
        <input
          autoFocus
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Add /stats endpoint returning user count"
          className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-indigo-500"
        />

        <label className="mt-4 block text-xs uppercase tracking-wide text-zinc-500">body</label>
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={8}
          placeholder={`Add a GET /stats endpoint to app/main.py that returns {"user_count": N} where N is len(USERS). Add a test in tests/test_main.py asserting status 200 and the correct count.`}
          className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 px-3 py-2 font-mono text-xs text-zinc-100 outline-none focus:border-indigo-500"
        />

        {error && (
          <div className="mt-3 rounded border border-rose-700/40 bg-rose-500/5 p-2 text-xs text-rose-300">
            {error}
          </div>
        )}

        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-zinc-700 px-3 py-1.5 text-sm text-zinc-300 hover:bg-zinc-800"
          >
            cancel
          </button>
          <button
            type="submit"
            disabled={busy}
            className="rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {busy ? "submitting..." : "submit ticket"}
          </button>
        </div>

        <p className="mt-3 text-[11px] text-zinc-500">
          Pre-flight rejects tickets containing live-shaped secrets (Stripe, OpenAI, AWS, etc.).
          Move secrets to env vars or reference them by name only.
        </p>
      </form>
    </div>
  );
}
