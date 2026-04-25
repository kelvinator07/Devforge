/**
 * Typed fetch wrapper for the DevForge control plane.
 *
 * Browser side: every call attaches the Clerk session JWT via Authorization.
 * Server side (getServerSideProps): Clerk's `auth()` from `@clerk/nextjs/server`
 * provides the token, but for v1 we keep the dashboard purely client-rendered
 * to keep the auth path simple. All `cpFetch` calls happen in useEffect.
 */
import { useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";

export const API = process.env.NEXT_PUBLIC_DEVFORGE_API || "http://localhost:8001";
export const ADMIN_TOKEN = process.env.NEXT_PUBLIC_DEVFORGE_ADMIN_TOKEN || "";

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

/** Hook: typed wrapper for a one-shot GET. Returns {data, loading, error, refresh}. */
export function useApi<T>(path: string | null) {
  const { getToken } = useAuth();
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!path) return;
    setLoading(true);
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
    }
  }, [path, getToken]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { data, loading, error, refresh };
}

/** POST /approvals — admin-token-gated. Returns the minted token. */
export async function mintApproval(approvalCommand: string): Promise<{ token: string }> {
  if (!ADMIN_TOKEN) {
    throw new Error("NEXT_PUBLIC_DEVFORGE_ADMIN_TOKEN not set in frontend .env.local");
  }
  const r = await fetch(`${API}/approvals`, {
    method: "POST",
    headers: {
      "X-Admin-Token": ADMIN_TOKEN,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ command: approvalCommand }),
  });
  if (!r.ok) throw new Error(`mint approval failed: ${r.status} ${await r.text()}`);
  return r.json() as Promise<{ token: string }>;
}
