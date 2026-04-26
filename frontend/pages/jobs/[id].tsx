import { SignedIn, SignedOut, RedirectToSignIn, UserButton, useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useRef, useState } from "react";

import { useApi, langfuseTraceUrl, type JobEvent } from "../../lib/api";
import { tailJob, type IncomingEvent } from "../../lib/sse";
import { EventCard, EventCardSkeleton } from "../../components/EventCard";
import { StatusBadge } from "../../components/StatusBadge";

const TERMINAL_STATUSES = new Set([
  "pr_opened",
  "failed",
  "refused",
  "awaiting_approval",
  "approval_superseded",
]);

type JobSnapshot = {
  job: { id: number; tenant_id: number; ticket_title: string; status: string; pr_url: string | null; created_at: string };
  events: JobEvent[];
};

export default function JobPage() {
  return (
    <>
      <SignedOut>
        <RedirectToSignIn />
      </SignedOut>
      <SignedIn>
        <JobPageInner />
      </SignedIn>
    </>
  );
}

function JobPageInner() {
  const router = useRouter();
  const jobId = Number(router.query.id);
  const { getToken } = useAuth();
  // Poll the snapshot every 3s so the status badge tracks the row in real
  // time (queued → pr_opened / failed). useApi suppresses the "loading…"
  // flash on background polls, and the status changes are infrequent
  // (one transition per job lifetime), so there's no flicker.
  const snapshot = useApi<JobSnapshot>(
    jobId ? `/jobs/${jobId}` : null,
    { pollMs: 3000 },
  );

  const [liveEvents, setLiveEvents] = useState<IncomingEvent[]>([]);
  const [closed, setClosed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seenIds = useRef<Set<number>>(new Set());
  const bottomRef = useRef<HTMLDivElement>(null);

  // Open SSE once we know the job id.
  useEffect(() => {
    if (!jobId || Number.isNaN(jobId)) return;
    setLiveEvents([]);
    seenIds.current = new Set();
    setClosed(false);
    setError(null);

    const stop = tailJob({
      jobId,
      getToken,
      onEvent(e) {
        if (seenIds.current.has(e.id)) return;
        seenIds.current.add(e.id);
        setLiveEvents((prev) => [...prev, e]);
      },
      onClose() {
        setClosed(true);
        // Re-fetch the snapshot so the status badge + PR button reflect
        // the final row (status="pr_opened" / pr_url=...). Without this
        // the badge stays "queued" because useApi doesn't auto-poll.
        snapshot.refresh();
      },
      onError(err) { setError(String(err)); },
    });
    return stop;
  }, [jobId, getToken, snapshot.refresh]);

  // Auto-scroll on new events.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [liveEvents.length]);

  if (!jobId) return <div className="p-8 text-zinc-500">missing job id</div>;

  // Merge snapshot events + live, dedup by id.
  const merged: IncomingEvent[] = [];
  const seen = new Set<number>();
  for (const e of snapshot.data?.events ?? []) {
    if (seen.has(e.id)) continue;
    seen.add(e.id);
    let data: Record<string, unknown> = {};
    try { data = JSON.parse(e.payload || "{}"); } catch {}
    merged.push({ id: e.id, type: e.event, data });
  }
  for (const e of liveEvents) {
    if (seen.has(e.id)) continue;
    seen.add(e.id);
    merged.push(e);
  }
  merged.sort((a, b) => a.id - b.id);

  // Pull the LangFuse trace id off the `trace_started` event (emitted by the
  // orchestrator immediately after `cost_tracking_started`). Hidden when the
  // env var NEXT_PUBLIC_LANGFUSE_PROJECT_ID is unset.
  const traceStarted = merged.find((e) => e.type === "trace_started");
  const traceId = traceStarted?.data?.trace_id as string | undefined;
  const traceUrl = traceId ? langfuseTraceUrl(traceId) : null;

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <Link href="/dashboard" className="text-sm text-zinc-500 hover:text-zinc-300">← dashboard</Link>
          <h1 className="mt-1 text-2xl font-semibold">job #{jobId}</h1>
        </div>
        <UserButton />
      </header>

      {snapshot.data?.job && (
        <section className="mb-6 rounded border border-zinc-800 bg-[var(--card)] p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="text-xs uppercase tracking-wide text-zinc-500">ticket</div>
              <div className="mt-1 truncate text-base">{snapshot.data.job.ticket_title}</div>
            </div>
            <div className="shrink-0 flex items-center gap-2">
              <StatusBadge status={snapshot.data.job.status} />
              {traceUrl && (
                <a href={traceUrl} target="_blank" rel="noreferrer"
                   className="rounded border border-zinc-700 px-3 py-1 text-xs text-zinc-300 hover:bg-zinc-800"
                   title="Open this job's full agent trace on LangFuse">
                  view trace ↗
                </a>
              )}
              {snapshot.data.job.pr_url && (
                <a href={snapshot.data.job.pr_url} target="_blank" rel="noreferrer"
                   className="rounded bg-emerald-600 px-3 py-1 text-xs text-white hover:bg-emerald-500">
                  view PR ↗
                </a>
              )}
            </div>
          </div>
          <div className="mt-2 text-xs text-zinc-500">{snapshot.data.job.created_at}</div>
        </section>
      )}

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-medium">Events</h2>
          <span className="text-xs text-zinc-500">
            {merged.length} events · {closed ? "stream closed" : "live"}
          </span>
        </div>
        {error && (
          <div className="mb-3 rounded border border-rose-700/40 bg-rose-500/5 p-2 text-xs text-rose-300">
            SSE error: {error}
          </div>
        )}
        {(() => {
          const jobStatus = snapshot.data?.job?.status;
          const isTerminal =
            closed || (jobStatus !== undefined && TERMINAL_STATUSES.has(jobStatus));
          return (
            <div className="space-y-2">
              {merged.length === 0 && !error && !isTerminal && (
                <div className="text-xs text-zinc-500">
                  Spawning a Fargate task — first events typically arrive within
                  ~30 seconds (cold-start). The page polls every 1.5 s.
                </div>
              )}
              {merged.map((e) => (
                <EventCard key={e.id} id={e.id} type={e.type} data={e.data} />
              ))}
              {!isTerminal && !error && (
                <>
                  <EventCardSkeleton />
                  <EventCardSkeleton accent="border-l-zinc-800" />
                  <EventCardSkeleton accent="border-l-zinc-800" />
                  <EventCardSkeleton accent="border-l-zinc-800" />
                </>
              )}
              <div ref={bottomRef} />
            </div>
          );
        })()}
      </section>
    </div>
  );
}
