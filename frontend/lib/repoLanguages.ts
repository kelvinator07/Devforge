/**
 * Frontend-side primary-language detection for connected GitHub repos.
 *
 * The control plane returns repos as {id, full_name, default_branch} — no
 * language. To filter the picker to Python projects without a backend change,
 * we hit GitHub's public REST API directly from the browser, cache results in
 * localStorage with a 24h TTL, and surface a hook + filter helpers.
 *
 * Limits:
 *   - Public repos only. Private repos return 404 unauthenticated and are
 *     treated as unknown → hidden by the Python filter. Acceptable for v1.
 *   - 60 req/hour unauthenticated rate limit. On 403 we stop fetching and
 *     surface `rateLimited`; consumers should fall back to showing the
 *     un-filtered list rather than locking the user out.
 */
import { useEffect, useMemo, useState } from "react";

import type { Tenant } from "./api";

const CACHE_KEY = "devforge.repoLang.v1";
const TTL_MS = 24 * 60 * 60 * 1000;
const PYTHON = "python";

type Entry = { language: string | null; fetchedAt: number };
type Cache = Record<string, Entry>;

function readCache(): Cache {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(CACHE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Cache;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function writeCache(c: Cache): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(CACHE_KEY, JSON.stringify(c));
  } catch {
    /* quota exceeded — ignore; we'll just refetch next mount */
  }
}

async function fetchOne(fullName: string): Promise<string | null> {
  const r = await fetch(`https://api.github.com/repos/${fullName}`);
  if (r.status === 403) throw new Error("rate-limited");
  if (!r.ok) return null;
  const j = (await r.json()) as { language: string | null };
  return j.language ?? null;
}

export function isPythonLanguage(lang: string | null | undefined): boolean {
  return (lang ?? "").toLowerCase() === PYTHON;
}

/** Flatten all repo `full_name`s across a tenants list — the input shape
 * `useRepoLanguages` expects. Used by every page that wants to filter or
 * render repos by language. */
export function tenantRepoFullNames(tenants: Tenant[]): string[] {
  return tenants.flatMap((t) => t.repos.map((r) => r.full_name));
}

/** Filter tenants in place: drop non-Python repos from each tenant's `repos`
 * array. Tenants with zero Python repos remain in the list (with empty repos)
 * so the picker can still render their per-tenant header + empty hint. */
export function filterToPython(
  tenants: Tenant[],
  languages: Map<string, string | null>,
): Tenant[] {
  return tenants.map((t) => ({
    ...t,
    repos: t.repos.filter((r) => isPythonLanguage(languages.get(r.full_name))),
  }));
}

/** React hook: given a list of repo full_names, returns a map of language
 * results, a loading flag (true while fetches are in flight), and a
 * rateLimited flag (true if GitHub returned 403 during this run). */
export function useRepoLanguages(fullNames: string[]): {
  languages: Map<string, string | null>;
  loading: boolean;
  rateLimited: boolean;
} {
  const [languages, setLanguages] = useState<Map<string, string | null>>(new Map());
  const [loading, setLoading] = useState(false);
  const [rateLimited, setRateLimited] = useState(false);

  // Stable key: same set of full_names → same effect run, regardless of
  // parent re-renders or array identity churn.
  const key = useMemo(() => [...fullNames].sort().join("|"), [fullNames]);

  useEffect(() => {
    if (!key) {
      setLanguages(new Map());
      setLoading(false);
      setRateLimited(false);
      return;
    }
    const names = key.split("|");
    const cache = readCache();
    const now = Date.now();
    const fresh = new Map<string, string | null>();
    const stale: string[] = [];
    for (const fn of names) {
      const e = cache[fn];
      if (e && now - e.fetchedAt < TTL_MS) fresh.set(fn, e.language);
      else stale.push(fn);
    }
    setLanguages(fresh);
    setRateLimited(false);
    if (!stale.length) {
      setLoading(false);
      return;
    }
    setLoading(true);
    let cancelled = false;
    (async () => {
      try {
        // Sequential, not Promise.all: a 403 should short-circuit the rest
        // before burning more rate-limit units.
        for (const fn of stale) {
          if (cancelled) return;
          try {
            const lang = await fetchOne(fn);
            if (cancelled) return;
            cache[fn] = { language: lang, fetchedAt: Date.now() };
            setLanguages((prev) => {
              const next = new Map(prev);
              next.set(fn, lang);
              return next;
            });
          } catch (e) {
            if (e instanceof Error && e.message === "rate-limited") {
              if (!cancelled) setRateLimited(true);
              return;
            }
            // Network error / parse failure: cache as null so we don't
            // hammer the same repo on every mount.
            cache[fn] = { language: null, fetchedAt: Date.now() };
            setLanguages((prev) => {
              const next = new Map(prev);
              next.set(fn, null);
              return next;
            });
          }
        }
      } finally {
        if (!cancelled) {
          writeCache(cache);
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [key]);

  return { languages, loading, rateLimited };
}
