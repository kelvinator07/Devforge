import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/router";
import { useEffect, useState } from "react";
import toast from "react-hot-toast";
import { X, Send } from "lucide-react";

import { submitTicket } from "../lib/api";
import { Button } from "./ui/Button";
import { Input, Textarea, Label } from "./ui/Input";

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

  // Esc-to-close + lock body scroll while open.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, busy, onClose]);

  if (!open) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !body.trim()) {
      setError("Title and body are required.");
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
      toast.success(`Ticket submitted · job #${job_id}`);
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 animate-fade-in"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="new-ticket-title"
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
        className="w-full max-w-2xl rounded-lg border border-[var(--border-strong)] bg-[var(--card)] p-6 shadow-2xl animate-scale-in"
      >
        <div className="mb-5 flex items-start justify-between">
          <div>
            <h2 id="new-ticket-title" className="text-[var(--text-h2)] font-semibold text-zinc-100">
              New ticket
            </h2>
            <p className="mt-0.5 text-xs text-zinc-500">
              Tickets are scanned for secrets before any agent runs.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="focus-ring rounded-md p-1 text-zinc-500 transition-colors hover:bg-zinc-800/60 hover:text-zinc-200"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <Label htmlFor="ticket-title">Title</Label>
            <Input
              id="ticket-title"
              autoFocus
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Add /stats endpoint returning user count"
            />
          </div>

          <div>
            <Label htmlFor="ticket-body" hint={`${body.length} chars`}>Body</Label>
            <Textarea
              id="ticket-body"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={9}
              placeholder={`Add a GET /stats endpoint to app/main.py that returns {"user_count": N} where N is len(USERS). Add a test in tests/test_main.py asserting status 200 and the correct count.`}
              className="font-mono text-xs"
            />
          </div>
        </div>

        {error && (
          <div className="mt-4 rounded-md border border-rose-500/40 bg-rose-500/5 p-2.5 text-xs text-rose-300">
            {error}
          </div>
        )}

        <div className="mt-6 flex items-center justify-between gap-3">
          <p className="text-[11px] text-zinc-500">
            Press <kbd className="rounded border border-zinc-700 bg-zinc-900 px-1 py-px font-mono text-[10px]">Esc</kbd> to cancel.
          </p>
          <div className="flex items-center gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              loading={busy}
              leftIcon={!busy ? <Send className="h-3.5 w-3.5" /> : undefined}
            >
              {busy ? "Submitting…" : "Submit ticket"}
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
}
