/**
 * Active tenant + repo store, plus the GitHub install handshake.
 *
 * Persistence: localStorage with a URL-param fallback for deep links.
 * Subscribers re-render when active changes (custom event + cross-tab
 * `storage` event).
 */
import { useEffect, useState } from "react";

import { type Tenant, GITHUB_APP_SLUG, githubInstallUrl } from "./api";
import { isPythonLanguage } from "./repoLanguages";

export const STATE_KEY = "devforge.install.state";
const STORAGE_KEY = "devforge.active";
const EVENT = "devforge:active-change";

export type Active = { tenantId: number; repoId: number };

function readFromStorage(): Active | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Active;
    if (typeof parsed.tenantId === "number" && typeof parsed.repoId === "number") {
      return parsed;
    }
  } catch { /* fall through */ }
  return null;
}

function readFromUrl(): Active | null {
  if (typeof window === "undefined") return null;
  const params = new URLSearchParams(window.location.search);
  const t = Number(params.get("tenant"));
  const r = Number(params.get("repo"));
  if (Number.isFinite(t) && t > 0 && Number.isFinite(r) && r > 0) {
    return { tenantId: t, repoId: r };
  }
  return null;
}

export function getActive(): Active | null {
  if (typeof window === "undefined") return null;
  return readFromUrl() ?? readFromStorage();
}

export function setActive(active: Active | null): void {
  if (typeof window === "undefined") return;
  // No-op guard: same value → don't write or dispatch.
  const current = readFromStorage();
  if (
    active === null
      ? current === null
      : current?.tenantId === active.tenantId && current?.repoId === active.repoId
  ) return;

  if (active === null) {
    window.localStorage.removeItem(STORAGE_KEY);
  } else {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(active));
  }
  window.dispatchEvent(new CustomEvent(EVENT, { detail: active }));
}

/** React hook — re-renders on any active change in this tab or other tabs. */
export function useActive(): Active | null {
  const [active, setLocal] = useState<Active | null>(() => getActive());
  useEffect(() => {
    // If we got the value from URL params on first read, promote it into
    // localStorage now (a side-effect that doesn't belong in the getter).
    const fromUrl = readFromUrl();
    if (fromUrl) setActive(fromUrl);

    const onChange = () => setLocal(getActive());
    window.addEventListener(EVENT, onChange);
    window.addEventListener("storage", onChange);
    return () => {
      window.removeEventListener(EVENT, onChange);
      window.removeEventListener("storage", onChange);
    };
  }, []);
  return active;
}

/** Resolve {tenant, repo} from a tenants list + the active store. Falls back
 * to the first tenant's first repo when active is unset/stale.
 *
 * When `languages` is supplied, only repos whose primary language is Python
 * are eligible — both the active pin and the fallback respect the filter.
 * Returns null if no tenant has any allowed repo. Without `languages`,
 * behavior is unchanged. */
export function resolveActive(
  tenants: Tenant[],
  active: Active | null,
  languages?: Map<string, string | null>,
): { tenant: Tenant; repoId: number } | null {
  if (!tenants.length) return null;
  const isAllowed = (r: { full_name: string }): boolean =>
    !languages || isPythonLanguage(languages.get(r.full_name));

  const tenant =
    (active && tenants.find((t) => t.id === active.tenantId && t.repos.some(isAllowed))) ??
    tenants.find((t) => t.repos.some(isAllowed));
  if (!tenant) return null;

  const allowed = tenant.repos.filter(isAllowed);
  const repo =
    (active && active.tenantId === tenant.id
      ? allowed.find((r) => r.id === active.repoId)
      : null) ?? allowed[0];
  return { tenant, repoId: repo.id };
}

/** Mint a CSRF state token, stash it, and redirect to GitHub's install
 * page. No-op if NEXT_PUBLIC_GITHUB_APP_SLUG isn't configured. */
export function startGithubInstall(): void {
  if (typeof window === "undefined" || !GITHUB_APP_SLUG) return;
  const state =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2) + Date.now().toString(36);
  window.sessionStorage.setItem(STATE_KEY, state);
  const url = githubInstallUrl(state);
  if (url) window.location.href = url;
}

/** Pop the install state token (one-time use). Returns null if missing. */
export function consumeInstallState(): string | null {
  if (typeof window === "undefined") return null;
  const state = window.sessionStorage.getItem(STATE_KEY);
  if (state) window.sessionStorage.removeItem(STATE_KEY);
  return state;
}
