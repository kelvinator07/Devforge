/**
 * Typed fetch wrapper for the DevForge control plane.
 *
 * Browser side: every call attaches the Clerk session JWT via Authorization.
 * Server side (getServerSideProps): Clerk's `auth()` from `@clerk/nextjs/server`
 * provides the token, but for v1 we keep the dashboard purely client-rendered
 * to keep the auth path simple. All `cpFetch` calls happen in useEffect.
 */
import { useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useRef, useState } from "react";

export const API = process.env.NEXT_PUBLIC_DEVFORGE_API || "http://localhost:8001";
export const ADMIN_TOKEN = process.env.NEXT_PUBLIC_DEVFORGE_ADMIN_TOKEN || "";
export const LANGFUSE_HOST = process.env.NEXT_PUBLIC_LANGFUSE_HOST || "https://cloud.langfuse.com";
export const LANGFUSE_PROJECT_ID = process.env.NEXT_PUBLIC_LANGFUSE_PROJECT_ID || "";

/** Build a deep link to a trace on LangFuse. Returns null when the project id
 * isn't configured — the UI falls back to hiding the link.
 * The Agents SDK emits ids as `trace_<32 hex>`; LangFuse stores them under the
 * 32-hex form (OTel format). Strip the prefix so the URL matches. */
export function langfuseTraceUrl(traceId: string): string | null {
  if (!LANGFUSE_PROJECT_ID || !traceId) return null;
  const lfId = traceId.startsWith("trace_") ? traceId.slice("trace_".length) : traceId;
  return `${LANGFUSE_HOST}/project/${LANGFUSE_PROJECT_ID}/traces/${lfId}`;
}

export type Tenant = {
  id: number;
  name: string;
  github_owner: string;
  github_installation_id: number;
  created_at: string;
  repos: { id: number; full_name: string; default_branch: string }[];
};

export type Job = {
  id: number;
  tenant_id: number;
  ticket_title: string;
  status: string;
  pr_url: string | null;
  created_at: string;
};

export type JobEvent = {
  id: number;
  event: string;
  payload: string; // JSON string
  ts: string;
};

export type PendingApproval = {
  id: number;
  tenant_id: number;
  ticket_title: string;
  ticket_body: string;
  approval_command: string | null;
  created_at: string;
};

/** Build headers including the Clerk JWT (when available). */
async function buildHeaders(getToken: () => Promise<string | null>): Promise<HeadersInit> {
  const headers: Record<string, string> = {};
  const tok = await getToken();
  if (tok) headers["Authorization"] = `Bearer ${tok}`;
  return headers;
}

/** Hook: typed wrapper for a one-shot GET. Returns {data, loading, error, refresh}.
 * Pass `{ pollMs: 3000 }` to background-poll the endpoint on a fixed interval.
 * Polling pauses when the tab is hidden; the spinner only shows on the very
 * first load so background refreshes are silent. */
export function useApi<T>(path: string | null, opts?: { pollMs?: number }) {
  const { getToken } = useAuth();
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const initialLoad = useRef(true);

  const refresh = useCallback(async () => {
    if (!path) return;
    if (initialLoad.current) setLoading(true);
    setError(null);
    try {
      const headers = await buildHeaders(getToken);
      const r = await fetch(`${API}${path}`, { headers });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const j = (await r.json()) as T;
      setData(j);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
      initialLoad.current = false;
    }
  }, [path, getToken]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!opts?.pollMs || !path) return;
    const tick = setInterval(() => {
      if (typeof document === "undefined" || document.visibilityState === "visible") {
        refresh();
      }
    }, opts.pollMs);
    return () => clearInterval(tick);
  }, [refresh, opts?.pollMs, path]);

  return { data, loading, error, refresh };
}

/** POST /jobs — submit a ticket through the full crew. Returns the new job id.
 * Pre-flight rejects tickets with embedded secrets via 422; the caller surfaces
 * those as form errors. */
export async function submitTicket(
  getToken: () => Promise<string | null>,
  body: { tenant_id: number; ticket_title: string; ticket_body: string; ticket_id?: string; approval_token?: string },
): Promise<{ job_id: number }> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const tok = await getToken();
  if (tok) headers["Authorization"] = `Bearer ${tok}`;
  const r = await fetch(`${API}/jobs`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    let detail: unknown = null;
    try { detail = (await r.json()).detail; } catch { /* not JSON */ }
    if (r.status === 422 && detail && typeof detail === "object") {
      const d = detail as { reason?: string; findings?: { summary?: string }[] };
      const summaries = (d.findings ?? []).map((f) => f.summary).filter(Boolean).join("; ");
      throw new Error(`${d.reason ?? "rejected"}: ${summaries || "see findings"}`);
    }
    throw new Error(`submit ticket failed: ${r.status} ${typeof detail === "string" ? detail : await r.text()}`);
  }
  return r.json() as Promise<{ job_id: number }>;
}


/** POST /approvals/run — admin-token-gated. Mints a token AND immediately
 * spawns a fresh run of the ticket; returns the new job_id so the caller
 * can navigate straight to its live event stream. */
export async function mintApprovalAndRun(req: {
  command: string;
  tenant_id: number;
  ticket_title: string;
  ticket_body: string;
  ticket_id?: string;
}): Promise<{ token: string; command: string; job_id: number }> {
  if (!ADMIN_TOKEN) {
    throw new Error("NEXT_PUBLIC_DEVFORGE_ADMIN_TOKEN not set in frontend .env.local");
  }
  const r = await fetch(`${API}/approvals/run`, {
    method: "POST",
    headers: {
      "X-Admin-Token": ADMIN_TOKEN,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(req),
  });
  if (!r.ok) throw new Error(`mint+run failed: ${r.status} ${await r.text()}`);
  return r.json() as Promise<{ token: string; command: string; job_id: number }>;
}
