/**
 * Typed clients for the per-repo RAG indexing endpoints + a thin SSE
 * subscriber that delegates to the generic tailEventStream.
 *
 * Endpoints (control_plane/main.py):
 *   GET  /repos/{id}/index-status     → IndexStatus
 *   POST /repos/{id}/index            → {index_job_id, already_running}
 *   GET  /index-jobs/{id}             → snapshot + events
 *   GET  /index-jobs/{id}/sse         → live event stream
 */
import { API, buildHeaders, readErrorBody } from "./api";
import { tailEventStream, type IncomingEvent } from "./sse";

export type IndexJobStatus = "queued" | "running" | "completed" | "failed";

export type IndexStatus = {
  indexed: boolean;
  last_indexed_at: string | null;
  latest_job_id: number | null;
  latest_status: IndexJobStatus | null;
  files_indexed: number | null;
  chunks_written: number | null;
  error: string | null;
};

export type IndexJobEvent = {
  id: number;
  event: string;
  payload: string; // JSON string
  ts: string;
};

export type IndexJob = {
  id: number;
  tenant_id: number;
  repo_id: number;
  status: IndexJobStatus;
  files_indexed: number | null;
  chunks_written: number | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type IndexJobSnapshot = {
  job: IndexJob;
  events: IndexJobEvent[];
};

const INDEX_TERMINAL_STATUS: ReadonlySet<string> = new Set(["completed", "failed"]);

async function readErrorMessage(r: Response, label: string): Promise<string> {
  const detail = await readErrorBody(r);
  return `${label}: ${r.status} ${typeof detail === "string" ? detail : ""}`.trim();
}

export async function fetchIndexStatus(
  getToken: () => Promise<string | null>,
  repoId: number,
): Promise<IndexStatus> {
  const headers = await buildHeaders(getToken);
  const r = await fetch(`${API}/repos/${repoId}/index-status`, { headers });
  if (!r.ok) throw new Error(await readErrorMessage(r, "index-status failed"));
  return r.json() as Promise<IndexStatus>;
}

export async function startIndexJob(
  getToken: () => Promise<string | null>,
  repoId: number,
): Promise<{ index_job_id: number; already_running: boolean }> {
  const headers = await buildHeaders(getToken, { "Content-Type": "application/json" });
  const r = await fetch(`${API}/repos/${repoId}/index`, {
    method: "POST",
    headers,
  });
  if (!r.ok) throw new Error(await readErrorMessage(r, "start index failed"));
  return r.json() as Promise<{ index_job_id: number; already_running: boolean }>;
}

export async function fetchIndexJob(
  getToken: () => Promise<string | null>,
  indexJobId: number,
): Promise<IndexJobSnapshot> {
  const headers = await buildHeaders(getToken);
  const r = await fetch(`${API}/index-jobs/${indexJobId}`, { headers });
  if (!r.ok) throw new Error(await readErrorMessage(r, "fetch index-job failed"));
  return r.json() as Promise<IndexJobSnapshot>;
}

export type TailIndexJobOpts = {
  indexJobId: number;
  getToken: () => Promise<string | null>;
  onEvent: (e: IncomingEvent) => void;
  onClose?: () => void;
  onError?: (err: unknown) => void;
};

export function tailIndexJob(opts: TailIndexJobOpts): () => void {
  return tailEventStream({
    ssePath: `/index-jobs/${opts.indexJobId}/sse`,
    pollPath: `/index-jobs/${opts.indexJobId}`,
    terminalStatuses: INDEX_TERMINAL_STATUS,
    getToken: opts.getToken,
    onEvent: opts.onEvent,
    onClose: opts.onClose,
    onError: opts.onError,
  });
}
