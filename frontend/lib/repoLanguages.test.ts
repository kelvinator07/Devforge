/**
 * Unit tests for the pure helpers in repoLanguages.ts. The React hook
 * (useRepoLanguages) needs jsdom + @testing-library/react, which the rest
 * of this suite doesn't carry, so it's covered manually via the dashboard.
 */
import { describe, expect, it } from "vitest";

import { filterToPython, isPythonLanguage } from "./repoLanguages";
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
