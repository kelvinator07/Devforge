/**
 * Event-stream tail — two implementations, same shape.
 *
 *   SSE (default, used locally with uvicorn): @microsoft/fetch-event-source
 *   so we can attach a Clerk JWT in the Authorization header (browser-
 *   native EventSource can't set headers).
 *
 *   Polling (used on AWS via NEXT_PUBLIC_DEVFORGE_USE_POLLING=1): a 1.5s
 *   GET {pollPath}?since_event_id=N loop. AWS API Gateway HTTP API buffers
 *   the streaming SSE response so SSE is a non-starter there; polling
 *   delivers the same UX with ~1.5s extra latency per event.
 *
 * `tailJob` (ticket runs) and `tailIndexJob` (RAG indexing) both delegate
 * to `tailEventStream` so adding a new event source is just picking the
 * paths + terminal-status set.
 */
import { fetchEventSource } from "@microsoft/fetch-event-source";

import { API } from "./api";

export type IncomingEvent = {
  id: number;
  type: string;
  data: Record<string, unknown>;
};

const JOB_TERMINAL_STATUS = new Set([
  "pr_opened",
  "failed",
  "refused",
  "awaiting_approval",
  "approval_superseded",
]);

const USE_POLLING = process.env.NEXT_PUBLIC_DEVFORGE_USE_POLLING === "1";
const POLL_INTERVAL_MS = 1500;

export type TailEventStreamOpts = {
  ssePath: string;   // e.g. /jobs/123/sse
  pollPath: string;  // e.g. /jobs/123 — must accept ?since_event_id=N
  terminalStatuses: ReadonlySet<string>;
  getToken: () => Promise<string | null>;
  onEvent: (e: IncomingEvent) => void;
  onClose?: () => void;
  onError?: (err: unknown) => void;
};

/** Generic event-stream consumer. SSE locally, long-poll on AWS. */
export function tailEventStream(opts: TailEventStreamOpts): () => void {
  return USE_POLLING ? pollStream(opts) : sseStream(opts);
}

// ---------- SSE (local) ----------

function sseStream(opts: TailEventStreamOpts): () => void {
  const ctrl = new AbortController();
  (async () => {
    const tok = await opts.getToken();
    const headers: Record<string, string> = { Accept: "text/event-stream" };
    if (tok) headers["Authorization"] = `Bearer ${tok}`;

    try {
      await fetchEventSource(`${API}${opts.ssePath}`, {
        headers,
        signal: ctrl.signal,
        openWhenHidden: true,
        onmessage(msg) {
          let data: Record<string, unknown> = {};
          try {
            data = JSON.parse(msg.data || "{}");
          } catch { /* ignore parse errors */ }
          opts.onEvent({
            id: Number(msg.id) || 0,
            type: msg.event || "message",
            data,
          });
        },
        onclose() {
          opts.onClose?.();
        },
        onerror(err) {
          opts.onError?.(err);
          throw err; // throwing stops the library's auto-retry
        },
      });
    } catch (err) {
      if ((err as Error)?.name === "AbortError") return;
      opts.onError?.(err);
    }
  })();
  return () => ctrl.abort();
}

// ---------- Polling (AWS) ----------

function pollStream(opts: TailEventStreamOpts): () => void {
  let sinceEventId = 0;
  let stopped = false;
  const ctrl = new AbortController();

  async function tick() {
    if (stopped) return;
    try {
      const tok = await opts.getToken();
      const headers: Record<string, string> = {};
      if (tok) headers["Authorization"] = `Bearer ${tok}`;
      const r = await fetch(
        `${API}${opts.pollPath}?since_event_id=${sinceEventId}`,
        { headers, signal: ctrl.signal },
      );
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);

      const body = (await r.json()) as {
        job: { status?: string };
        events: { id: number; event: string; payload: string }[];
      };

      for (const e of body.events ?? []) {
        if (e.id > sinceEventId) sinceEventId = e.id;
        let data: Record<string, unknown> = {};
        try { data = JSON.parse(e.payload || "{}"); } catch { /* ignore */ }
        opts.onEvent({ id: e.id, type: e.event, data });
      }

      if (body.job?.status && opts.terminalStatuses.has(body.job.status)) {
        stopped = true;
        opts.onClose?.();
      }
    } catch (err) {
      if ((err as Error)?.name === "AbortError") return;
      opts.onError?.(err);
    }
  }

  tick(); // first fetch immediately, no 1.5s wait
  const handle = setInterval(tick, POLL_INTERVAL_MS);

  return () => {
    stopped = true;
    clearInterval(handle);
    ctrl.abort();
  };
}

// ---------- Job-specific wrapper (kept for back-compat) ----------

export type TailJobOpts = {
  jobId: number;
  getToken: () => Promise<string | null>;
  onEvent: (e: IncomingEvent) => void;
  onClose?: () => void;
  onError?: (err: unknown) => void;
};

export function tailJob(opts: TailJobOpts): () => void {
  return tailEventStream({
    ssePath: `/jobs/${opts.jobId}/sse`,
    pollPath: `/jobs/${opts.jobId}`,
    terminalStatuses: JOB_TERMINAL_STATUS,
    getToken: opts.getToken,
    onEvent: opts.onEvent,
    onClose: opts.onClose,
    onError: opts.onError,
  });
}
