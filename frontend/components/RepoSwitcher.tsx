import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronsUpDown, Check, Github, Plus } from "lucide-react";

import { GITHUB_APP_SLUG, useApi, type Tenant } from "../lib/api";
import { setActive, startGithubInstall, useActive } from "../lib/active";

/** Top-nav repo picker. Lists every (tenant, repo) the signed-in Clerk
 * user has connected, grouped by tenant. Click sets active; "+ Connect
 * another GitHub account/org" re-runs the install flow. */
export function RepoSwitcher() {
  const tenants = useApi<{ tenants: Tenant[] }>("/tenants/mine");
  const active = useActive();
  const [open, setOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  // Close on outside click + Esc.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    const onClick = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  const list = tenants.data?.tenants ?? [];

  const activeRepoLabel = useMemo(() => {
    if (!active || !list.length) return null;
    const t = list.find((tt) => tt.id === active.tenantId);
    if (!t) return null;
    const r = t.repos.find((rr) => rr.id === active.repoId);
    return r ? r.full_name : null;
  }, [active, list]);

  // Hide entirely until we know whether the user has any tenants.
  if (!tenants.data) return null;
  // No tenants yet — the dashboard's empty-state handles connect.
  if (!list.length) return null;

  return (
    <div ref={popoverRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className={[
          "focus-ring inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs",
          "transition-colors duration-[var(--dur-fast)] ease-[var(--ease)]",
          "border-[var(--border)] text-zinc-300 hover:border-[var(--border-strong)] hover:bg-zinc-800/40 hover:text-zinc-100",
        ].join(" ")}
      >
        <Github className="h-3 w-3 text-zinc-500" />
        <span className="font-mono">{activeRepoLabel ?? "Pick a repo"}</span>
        <ChevronsUpDown className="h-3 w-3 text-zinc-500" />
      </button>

      {open && (
        <div
          className="absolute left-0 top-full z-40 mt-1 min-w-[280px] rounded-lg border border-[var(--border-strong)] bg-[var(--card)] p-1 shadow-2xl animate-fade-in"
          role="listbox"
        >
          <div className="max-h-72 overflow-y-auto py-1">
            {list.map((t) => (
              <div key={t.id} className="pb-1">
                <div className="px-2 pt-1.5 pb-1 text-[10px] uppercase tracking-wider text-zinc-500">
                  {t.github_owner}
                </div>
                {t.repos.length === 0 && (
                  <div className="px-3 pb-1 text-xs text-zinc-600 italic">
                    no repos in this install
                  </div>
                )}
                {t.repos.map((r) => {
                  const isActive =
                    active?.tenantId === t.id && active?.repoId === r.id;
                  return (
                    <button
                      key={r.id}
                      type="button"
                      onClick={() => {
                        setActive({ tenantId: t.id, repoId: r.id });
                        setOpen(false);
                      }}
                      className={[
                        "focus-ring flex w-full items-center justify-between gap-3 rounded-md px-2 py-1.5 text-left text-xs",
                        "transition-colors duration-[var(--dur-fast)] ease-[var(--ease)]",
                        isActive
                          ? "bg-indigo-500/10 text-indigo-200"
                          : "text-zinc-300 hover:bg-zinc-800/60 hover:text-zinc-100",
                      ].join(" ")}
                      role="option"
                      aria-selected={isActive}
                    >
                      <span className="truncate font-mono">{r.full_name}</span>
                      {isActive && <Check className="h-3 w-3 shrink-0 text-indigo-300" />}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
          {GITHUB_APP_SLUG && (
            <div className="border-t border-[var(--border)] pt-1">
              <button
                type="button"
                onClick={() => {
                  setOpen(false);
                  startGithubInstall();
                }}
                className="focus-ring flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-xs text-indigo-300 transition-colors hover:bg-indigo-500/10"
              >
                <Plus className="h-3 w-3" />
                Connect another GitHub account/org
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
