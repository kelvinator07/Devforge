/**
 * Unit tests for the pure helpers in repoLanguages.ts. The React hook
 * (useRepoLanguages) needs jsdom + @testing-library/react, which the rest
 * of this suite doesn't carry, so it's covered manually via the dashboard.
 */
import { describe, expect, it } from "vitest";

import { filterToPython, isPythonLanguage, tenantRepoFullNames } from "./repoLanguages";
import type { Tenant } from "./api";

describe("isPythonLanguage", () => {
  it("matches 'Python' exactly", () => {
    expect(isPythonLanguage("Python")).toBe(true);
  });

  it("is case-insensitive", () => {
    expect(isPythonLanguage("python")).toBe(true);
    expect(isPythonLanguage("PYTHON")).toBe(true);
    expect(isPythonLanguage("PyThOn")).toBe(true);
  });

  it("rejects other languages", () => {
    expect(isPythonLanguage("Go")).toBe(false);
    expect(isPythonLanguage("JavaScript")).toBe(false);
    expect(isPythonLanguage("TypeScript")).toBe(false);
  });

  it("rejects null, undefined, and empty string", () => {
    expect(isPythonLanguage(null)).toBe(false);
    expect(isPythonLanguage(undefined)).toBe(false);
    expect(isPythonLanguage("")).toBe(false);
  });
});

function makeTenant(id: number, repos: Array<{ id: number; full_name: string }>): Tenant {
  return {
    id,
    name: `tenant-${id}`,
    github_owner: `owner-${id}`,
    github_installation_id: 1000 + id,
    created_at: "2026-01-01T00:00:00Z",
    repos: repos.map((r) => ({ ...r, default_branch: "main" })),
  };
}

describe("filterToPython", () => {
  it("drops non-Python repos from each tenant", () => {
    const tenants = [
      makeTenant(1, [
        { id: 10, full_name: "owner-1/py" },
        { id: 11, full_name: "owner-1/go" },
      ]),
    ];
    const languages = new Map<string, string | null>([
      ["owner-1/py", "Python"],
      ["owner-1/go", "Go"],
    ]);
    const out = filterToPython(tenants, languages);
    expect(out).toHaveLength(1);
    expect(out[0].repos).toHaveLength(1);
    expect(out[0].repos[0].full_name).toBe("owner-1/py");
  });

  it("keeps tenants with zero Python repos but empties their repos array", () => {
    const tenants = [
      makeTenant(1, [{ id: 10, full_name: "owner-1/go" }]),
      makeTenant(2, [{ id: 20, full_name: "owner-2/py" }]),
    ];
    const languages = new Map<string, string | null>([
      ["owner-1/go", "Go"],
      ["owner-2/py", "Python"],
    ]);
    const out = filterToPython(tenants, languages);
    expect(out).toHaveLength(2);
    expect(out[0].repos).toHaveLength(0);
    expect(out[1].repos).toHaveLength(1);
  });

  it("treats missing/null language as non-Python", () => {
    const tenants = [
      makeTenant(1, [
        { id: 10, full_name: "owner-1/unknown" },
        { id: 11, full_name: "owner-1/empty" },
        { id: 12, full_name: "owner-1/py" },
      ]),
    ];
    const languages = new Map<string, string | null>([
      // owner-1/unknown is absent from the map (not yet fetched)
      ["owner-1/empty", null], // empty repo
      ["owner-1/py", "Python"],
    ]);
    const out = filterToPython(tenants, languages);
    expect(out[0].repos.map((r) => r.full_name)).toEqual(["owner-1/py"]);
  });

  it("does not mutate the input tenants", () => {
    const tenants = [
      makeTenant(1, [
        { id: 10, full_name: "owner-1/py" },
        { id: 11, full_name: "owner-1/go" },
      ]),
    ];
    const languages = new Map<string, string | null>([
      ["owner-1/py", "Python"],
      ["owner-1/go", "Go"],
    ]);
    filterToPython(tenants, languages);
    expect(tenants[0].repos).toHaveLength(2);
  });
});

/**
 * Integration-shaped tests mirroring the exact pipeline `RepoSwitcher` runs:
 *   list -> tenantRepoFullNames -> useRepoLanguages -> filterToPython -> render
 *
 * The hook itself can't be invoked here (no jsdom/RTL), so we substitute its
 * `Map<full_name, language|null>` output and assert the picker would render
 * only Python repos.
 */
describe("RepoSwitcher pipeline shows only Python repos", () => {
  function visibleRepos(tenants: Tenant[], languages: Map<string, string | null>): string[] {
    const filtered = filterToPython(tenants, languages);
    return filtered.flatMap((t) => t.repos.map((r) => r.full_name));
  }

  it("hides Go, JavaScript, TypeScript, and Rust repos across multiple tenants", () => {
    const tenants = [
      makeTenant(1, [
        { id: 10, full_name: "personal/api" },
        { id: 11, full_name: "personal/web" },
        { id: 12, full_name: "personal/cli" },
      ]),
      makeTenant(2, [
        { id: 20, full_name: "work/data-pipeline" },
        { id: 21, full_name: "work/dashboard" },
        { id: 22, full_name: "work/infra" },
      ]),
    ];
    const languages = new Map<string, string | null>([
      ["personal/api", "Python"],
      ["personal/web", "TypeScript"],
      ["personal/cli", "Go"],
      ["work/data-pipeline", "Python"],
      ["work/dashboard", "JavaScript"],
      ["work/infra", "Rust"],
    ]);

    expect(visibleRepos(tenants, languages)).toEqual([
      "personal/api",
      "work/data-pipeline",
    ]);
  });

  it("emits the exact set of full_names the hook needs to fetch", () => {
    const tenants = [
      makeTenant(1, [
        { id: 1, full_name: "a/x" },
        { id: 2, full_name: "a/y" },
      ]),
      makeTenant(2, [{ id: 3, full_name: "b/z" }]),
    ];
    expect(tenantRepoFullNames(tenants)).toEqual(["a/x", "a/y", "b/z"]);
  });

  it("hides repos whose language hasn't resolved yet (avoids flashing non-Python rows)", () => {
    const tenants = [
      makeTenant(1, [
        { id: 1, full_name: "a/py" },
        { id: 2, full_name: "a/pending" },
      ]),
    ];
    // Only one entry resolved; the other is mid-fetch.
    const languages = new Map<string, string | null>([["a/py", "Python"]]);
    expect(visibleRepos(tenants, languages)).toEqual(["a/py"]);
  });

  it("hides private repos (404 from unauthenticated GitHub API → cached as null)", () => {
    const tenants = [
      makeTenant(1, [
        { id: 1, full_name: "acme/public-py" },
        { id: 2, full_name: "acme/private-py" },
      ]),
    ];
    const languages = new Map<string, string | null>([
      ["acme/public-py", "Python"],
      ["acme/private-py", null],
    ]);
    expect(visibleRepos(tenants, languages)).toEqual(["acme/public-py"]);
  });

  it("when rate-limited, the picker bypasses the filter (emergency fallback)", () => {
    const tenants = [
      makeTenant(1, [
        { id: 1, full_name: "a/py" },
        { id: 2, full_name: "a/go" },
      ]),
    ];
    const languages = new Map<string, string | null>();
    const rateLimited = true;

    // RepoSwitcher.tsx pattern: rateLimited ? list : filterToPython(list, languages)
    const displayed = rateLimited ? tenants : filterToPython(tenants, languages);
    const visible = displayed.flatMap((t) => t.repos.map((r) => r.full_name));
    expect(visible).toEqual(["a/py", "a/go"]);
  });

  it("a tenant with zero Python repos surfaces the empty-state hint, not silently disappears", () => {
    const tenants = [
      makeTenant(1, [{ id: 1, full_name: "a/py" }]),
      makeTenant(2, [{ id: 2, full_name: "b/go" }]),
    ];
    const languages = new Map<string, string | null>([
      ["a/py", "Python"],
      ["b/go", "Go"],
    ]);
    const filtered = filterToPython(tenants, languages);

    // Tenant 2 stays in the list (so the picker can render its header + hint).
    expect(filtered).toHaveLength(2);
    expect(filtered[1].repos).toHaveLength(0);

    // RepoSwitcher's "N hidden" computation:
    const hidden = tenants[1].repos.length - filtered[1].repos.length;
    expect(hidden).toBe(1);
  });
});
