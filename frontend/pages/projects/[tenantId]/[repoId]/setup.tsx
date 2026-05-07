import { SignedIn, SignedOut, RedirectToSignIn, useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { useRouter } from "next/router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Activity,
  CheckCircle2,
  AlertCircle,
  Database,
  RefreshCw,
} from "lucide-react";

import { useApi, type Tenant } from "../../../../lib/api";
import {
  fetchIndexStatus,
  startIndexJob,
  tailIndexJob,
  type IndexStatus,
} from "../../../../lib/indexJobs";
import { setActive } from "../../../../lib/active";
import { type IncomingEvent } from "../../../../lib/sse";
import { EventCard, EventCardSkeleton } from "../../../../components/EventCard";
import { Layout } from "../../../../components/Layout";
import { Card } from "../../../../components/ui/Card";
import { Button } from "../../../../components/ui/Button";
import { Spinner } from "../../../../components/ui/Spinner";

export default function ProjectSetup() {
  return (
    <>
      <SignedOut>
        <RedirectToSignIn />
      </SignedOut>
      <SignedIn>
        <ProjectSetupInner />
      </SignedIn>
    </>
  );
}

function ProjectSetupInner() {
  const router = useRouter();
  const { getToken } = useAuth();
  const tenantId = Number(router.query.tenantId);
  const repoId = Number(router.query.repoId);

  const tenants = useApi<{ tenants: Tenant[] }>("/tenants/mine");
  const tenant = tenants.data?.tenants.find((t) => t.id === tenantId) ?? null;
  const repo = tenant?.repos.find((r) => r.id === repoId) ?? null;

  const [status, setStatus] = useState<IndexStatus | null>(null);
  const [statusErr, setStatusErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Live event-stream state. activeJobId is the id of whichever job we're
  // tailing; null when no stream is open.
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [liveEvents, setLiveEvents] = useState<IncomingEvent[]>([]);
  const [streamClosed, setStreamClosed] = useState(false);
  const [streamErr, setStreamErr] = useState<string | null>(null);
  const seenIds = useRef<Set<number>>(new Set());

  const refreshStatus = useCallback(async () => {
    if (!Number.isFinite(repoId) || repoId <= 0) return;
    try {
      const s = await fetchIndexStatus(getToken, repoId);
      setStatus(s);
      if (
        s.latest_job_id &&
        (s.latest_status === "queued" || s.latest_status === "running")
      ) {
        setActiveJobId((cur) => cur ?? s.latest_job_id);
      }
    } catch (e: unknown) {
      setStatusErr(e instanceof Error ? e.message : String(e));
    }
  }, [getToken, repoId]);

  // Hold the latest refreshStatus in a ref so the SSE effect can call it
  // without listing it as a dependency — otherwise a stable-but-new closure
  // would tear down + reopen the EventSource on every render.
  const refreshStatusRef = useRef(refreshStatus);
  useEffect(() => {
    refreshStatusRef.current = refreshStatus;
  }, [refreshStatus]);

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  useEffect(() => {
    if (!activeJobId) return;
    setLiveEvents([]);
    seenIds.current = new Set();
    setStreamClosed(false);
    setStreamErr(null);

    const stop = tailIndexJob({
      indexJobId: activeJobId,
      getToken,
      onEvent(e) {
        if (seenIds.current.has(e.id)) return;
        seenIds.current.add(e.id);
        setLiveEvents((prev) => [...prev, e]);
      },
      onClose() {
        setStreamClosed(true);
        refreshStatusRef.current();
      },
      onError(err) {
        setStreamErr(String(err));
      },
    });
    return stop;
  }, [activeJobId, getToken]);

  async function onStartIndex() {
    if (!repo) return;
    setBusy(true);
    setStreamErr(null);
    try {
      const { index_job_id } = await startIndexJob(getToken, repoId);
      setActiveJobId(index_job_id);
      // Pull fresh status so the page swaps from "Index this repo" to the
      // live event view; the SSE effect attaches as soon as activeJobId flips.
      refreshStatus();
    } catch (e: unknown) {
      setStreamErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function onContinueToDashboard() {
    setActive({ tenantId, repoId });
    router.push("/dashboard");
  }

  // All hooks must be declared before any early return — keep these here.
  const showStream =
    activeJobId !== null && (!streamClosed || liveEvents.length > 0);
  const progress = useMemo(() => latestProgress(liveEvents), [liveEvents]);

  if (!tenants.data) {
    return (
      <Layout width="default">
        <div className="py-12 text-center">
          <Spinner size="lg" />
        </div>
      </Layout>
    );
  }
  if (!tenant || !repo) {
    return (
      <Layout width="default">
        <Card variant="danger">
          <div className="text-sm font-medium text-rose-200">
            Repo not found in your installs.
          </div>
          <div className="mt-1 text-xs text-zinc-400">
            tenant {tenantId} · repo {repoId}
          </div>
          <div className="mt-3">
            <Button size="sm" onClick={() => router.replace("/dashboard")}>
              Back to dashboard
            </Button>
          </div>
        </Card>
      </Layout>
    );
  }

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
          Set up <span className="font-mono text-zinc-400">{repo.full_name}</span>
        </h1>
        <p className="mt-1 text-xs text-zinc-500">
          tenant <span className="text-zinc-300">{tenant.name}</span> ·
          install <span className="font-mono text-zinc-300">{tenant.github_installation_id}</span>
        </p>
      </div>

      {statusErr && (
        <Card variant="danger" padding="sm" className="mb-4">
          <div className="text-xs text-rose-200">Couldn&apos;t load index status: {statusErr}</div>
        </Card>
      )}

      {/* Top status card */}
      {status && !showStream && status.indexed && (
        <Card variant="elevated" className="mb-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="inline-flex items-center gap-2 text-sm font-medium text-emerald-300">
                <CheckCircle2 className="h-4 w-4" />
                Indexed
              </div>
              <div className="mt-1 text-xs text-zinc-400">
                {status.last_indexed_at && (
                  <>last indexed {formatRelative(status.last_indexed_at)} · </>
                )}
                {status.files_indexed ?? "?"} files · {status.chunks_written ?? "?"} chunks
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                leftIcon={<RefreshCw className="h-3.5 w-3.5" />}
                loading={busy}
                onClick={onStartIndex}
              >
                Re-index
              </Button>
              <Button
                size="sm"
                rightIcon={<ArrowRight className="h-3.5 w-3.5" />}
                onClick={onContinueToDashboard}
              >
                Continue to dashboard
              </Button>
            </div>
          </div>
        </Card>
      )}

      {status && !showStream && !status.indexed && status.latest_status !== "failed" && (
        <Card variant="elevated" className="mb-6">
          <div className="flex items-start gap-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-[var(--border)] text-zinc-300">
              <Database className="h-4 w-4" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-zinc-100">
                This repo hasn&apos;t been indexed yet
              </div>
              <p className="mt-1 text-xs text-zinc-400">
                Indexing scans the repo, splits it into semantic chunks, and embeds
                them so agents can ground tickets in real code instead of
                hallucinating file paths. Runs in the background — you can leave
                this page and come back.
              </p>
              <div className="mt-3">
                <Button
                  size="sm"
                  loading={busy}
                  leftIcon={<Database className="h-3.5 w-3.5" />}
                  onClick={onStartIndex}
                >
                  Index this repo
                </Button>
              </div>
            </div>
          </div>
        </Card>
      )}

      {status && !showStream && status.latest_status === "failed" && (
        <Card variant="danger" className="mb-6">
          <div className="flex items-start gap-3">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-rose-400" />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-rose-200">
                Last indexing run failed
              </div>
              {status.error && (
                <pre className="mt-2 max-h-40 overflow-auto rounded border border-rose-500/30 bg-rose-500/5 p-2 text-[11px] text-rose-200">
                  {status.error}
                </pre>
              )}
              <div className="mt-3">
                <Button
                  size="sm"
                  loading={busy}
                  leftIcon={<RefreshCw className="h-3.5 w-3.5" />}
                  onClick={onStartIndex}
                >
                  Try again
                </Button>
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* Live event stream */}
      {showStream && (
        <section>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-[var(--text-h2)] font-semibold text-zinc-100">
              Indexing job <span className="font-mono text-zinc-400">#{activeJobId}</span>
            </h2>
            <span className="inline-flex items-center gap-1.5 text-xs text-zinc-500">
              <span className="font-mono tabular-nums">{liveEvents.length}</span>
              <span>·</span>
              {streamClosed ? (
                <span>stream closed</span>
              ) : (
                <span className="inline-flex items-center gap-1 text-emerald-400">
                  <Activity className="h-3 w-3 animate-pulse" />
                  live
                </span>
              )}
            </span>
          </div>

          {progress && (
            <Card padding="sm" className="mb-3">
              <div className="flex items-center justify-between text-xs text-zinc-400">
                <span>Embedding chunks</span>
                <span className="font-mono tabular-nums">
                  {progress.done} / {progress.total}
                </span>
              </div>
              <div className="mt-2 h-1.5 w-full overflow-hidden rounded bg-zinc-800">
                <div
                  className="h-full bg-indigo-500 transition-all"
                  style={{ width: `${Math.min(100, (progress.done / Math.max(1, progress.total)) * 100)}%` }}
                />
              </div>
            </Card>
          )}

          {streamErr && (
            <Card variant="danger" padding="sm" className="mb-3">
              <div className="text-xs text-rose-200">Stream error: {streamErr}</div>
            </Card>
          )}

          <div className="space-y-2">
            {liveEvents.length === 0 && !streamClosed && (
              <div className="rounded-md border border-dashed border-[var(--border)] px-4 py-3 text-xs text-zinc-500">
                Spawning the indexer — first events typically arrive within a few
                seconds. The stream auto-updates.
              </div>
            )}
            {liveEvents.map((e) => (
              <EventCard key={e.id} id={e.id} type={e.type} data={e.data} />
            ))}
            {!streamClosed && (
              <>
                <EventCardSkeleton />
                <EventCardSkeleton accent="border-l-zinc-800" />
              </>
            )}
          </div>

          {streamClosed && status?.indexed && (
            <div className="mt-4 flex justify-end">
              <Button
                size="sm"
                rightIcon={<ArrowRight className="h-3.5 w-3.5" />}
                onClick={onContinueToDashboard}
              >
                Continue to dashboard
              </Button>
            </div>
          )}
        </section>
      )}
    </Layout>
  );
}

function latestProgress(events: IncomingEvent[]): { done: number; total: number } | null {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].type === "embedding_progress") {
      const d = events[i].data;
      const done = Number(d.done);
      const total = Number(d.total);
      if (Number.isFinite(done) && Number.isFinite(total) && total > 0) {
        return { done, total };
      }
    }
  }
  return null;
}

function formatRelative(iso: string): string {
  try {
    const ms = Date.now() - new Date(iso).getTime();
    if (!Number.isFinite(ms) || ms < 0) return "just now";
    const s = Math.floor(ms / 1000);
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    const d = Math.floor(h / 24);
    return `${d}d ago`;
  } catch {
    return iso;
  }
}
