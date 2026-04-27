import { SignedIn, SignedOut, RedirectToSignIn, useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ExternalLink, GitPullRequest, Activity } from "lucide-react";

import { useApi, langfuseTraceUrl, type JobEvent } from "../../lib/api";
import { tailJob, type IncomingEvent } from "../../lib/sse";
import { EventCard, EventCardSkeleton } from "../../components/EventCard";
import { StatusBadge } from "../../components/StatusBadge";
import { Layout } from "../../components/Layout";
import { Card } from "../../components/ui/Card";
import { Button } from "../../components/ui/Button";

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
  const snapshot = useApi<JobSnapshot>(
    jobId ? `/jobs/${jobId}` : null,
    { pollMs: 3000 },
  );

  const [liveEvents, setLiveEvents] = useState<IncomingEvent[]>([]);
  const [closed, setClosed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seenIds = useRef<Set<number>>(new Set());
  const bottomRef = useRef<HTMLDivElement>(null);

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
        snapshot.refresh();
      },
      onError(err) {
        setError(String(err));
      },
    });
    return stop;
  }, [jobId, getToken, snapshot.refresh]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [liveEvents.length]);

  if (!jobId) {
    return (
      <Layout width="default">
        <div className="text-zinc-500">Missing job id.</div>
      </Layout>
    );
  }

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

  const traceStarted = merged.find((e) => e.type === "trace_started");
  const traceId = traceStarted?.data?.trace_id as string | undefined;
  const traceUrl = traceId ? langfuseTraceUrl(traceId) : null;

  const jobStatus = snapshot.data?.job?.status;
  const isTerminal = closed || (jobStatus !== undefined && TERMINAL_STATUSES.has(jobStatus));

  return (
    <Layout width="default">
      <div className="mb-6">
        <Link
          href="/dashboard"
          className="focus-ring inline-flex items-center gap-1 rounded-md text-xs text-zinc-500 no-underline hover:text-zinc-300"
        >
          <ArrowLeft className="h-3 w-3" />
          Dashboard
        </Link>
        <h1 className="mt-2 text-[var(--text-h1)] font-semibold tracking-tight text-zinc-100">
          Job <span className="font-mono text-zinc-400">#{jobId}</span>
        </h1>
      </div>

      {snapshot.data?.job && (
        <Card variant="elevated" className="mb-6">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <div className="text-xs uppercase tracking-wide text-zinc-500">Ticket</div>
              <div className="mt-1 truncate text-base font-medium text-zinc-100">
                {snapshot.data.job.ticket_title}
              </div>
              <div className="mt-2 text-xs text-zinc-500">
                {formatDate(snapshot.data.job.created_at)}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <StatusBadge status={snapshot.data.job.status} />
              {traceUrl && (
                <Button
                  variant="secondary"
                  size="sm"
                  leftIcon={<ExternalLink className="h-3.5 w-3.5" />}
                  onClick={() => window.open(traceUrl, "_blank", "noopener,noreferrer")}
                  title="Open this job's full agent trace on LangFuse"
                >
                  Trace
                </Button>
              )}
              {snapshot.data.job.pr_url && (
                <Button
                  size="sm"
                  leftIcon={<GitPullRequest className="h-3.5 w-3.5" />}
                  onClick={() => window.open(snapshot.data!.job.pr_url!, "_blank", "noopener,noreferrer")}
                >
                  View PR
                </Button>
              )}
            </div>
          </div>
        </Card>
      )}

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-[var(--text-h2)] font-semibold text-zinc-100">Events</h2>
          <span className="inline-flex items-center gap-1.5 text-xs text-zinc-500">
            <span className="font-mono tabular-nums">{merged.length}</span>
            <span>·</span>
            {closed ? (
              <span>stream closed</span>
            ) : (
              <span className="inline-flex items-center gap-1 text-emerald-400">
                <Activity className="h-3 w-3 animate-pulse" />
                live
              </span>
            )}
          </span>
        </div>

        {error && (
          <Card variant="danger" padding="sm" className="mb-3">
            <div className="text-xs text-rose-200">SSE error: {error}</div>
          </Card>
        )}

        <div className="space-y-2">
          {merged.length === 0 && !error && !isTerminal && (
            <div className="rounded-md border border-dashed border-[var(--border)] px-4 py-3 text-xs text-zinc-500">
              Spawning a Fargate task — first events typically arrive within ~30s (cold start).
              The page polls every 1.5s.
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
      </section>
    </Layout>
  );
}

function formatDate(s: string): string {
  try {
    return new Date(s).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return s;
  }
}
