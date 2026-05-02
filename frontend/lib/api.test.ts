/**
 * Unit tests for frontend/lib/api.ts — fetch wrappers + URL builders.
 *
 * Covers the pure helpers (langfuseTraceUrl) and the network functions
 * (submitTicket, mintApprovalAndRun) with a mocked global fetch. We do
 * NOT test the `useApi` React hook here — that needs @testing-library/react
 * + jsdom, which is deferred per the plan.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  connectInstallation,
  listMyTenants,
  langfuseTraceUrl,
  mintApprovalAndRun,
  submitTicket,
} from "./api";

describe("langfuseTraceUrl", () => {
  it("returns null when project id is missing", () => {
    // The module captured LANGFUSE_PROJECT_ID at import time; with no env var
    // set in the test environment, it defaults to "" → null.
    expect(langfuseTraceUrl("trace_abc")).toBeNull();
  });

  it("returns null for empty trace id", () => {
    expect(langfuseTraceUrl("")).toBeNull();
  });
});

describe("submitTicket", () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  it("POSTs to /jobs with bearer token and returns job_id", async () => {
    (global.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({ job_id: 42 }),
    });
    const getToken = vi.fn().mockResolvedValue("jwt-xyz");

    const res = await submitTicket(getToken, {
      tenant_id: 1,
      ticket_title: "title",
      ticket_body: "body",
    });

    expect(res.job_id).toBe(42);
    const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>;
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/jobs$/);
    expect(init.method).toBe("POST");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(init.headers.Authorization).toBe("Bearer jwt-xyz");
    expect(JSON.parse(init.body)).toEqual({
      tenant_id: 1,
      ticket_title: "title",
      ticket_body: "body",
    });
  });

  it("omits Authorization header when getToken returns null", async () => {
    (global.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({ job_id: 1 }),
    });
    const getToken = vi.fn().mockResolvedValue(null);

    await submitTicket(getToken, {
      tenant_id: 1,
      ticket_title: "t",
      ticket_body: "b",
    });

    const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>;
    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers.Authorization).toBeUndefined();
  });

  it("surfaces 422 secret-rejection findings as a thrown error", async () => {
    (global.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({
        detail: {
          reason: "ticket contains real-shaped secret(s)",
          findings: [
            { summary: "STRIPE_SECRET sk_live_…" },
            { summary: "GITHUB_PAT ghp_…" },
          ],
        },
      }),
      text: async () => "",
    });

    await expect(
      submitTicket(vi.fn().mockResolvedValue("tok"), {
        tenant_id: 1,
        ticket_title: "t",
        ticket_body: "b",
      }),
    ).rejects.toThrow(/STRIPE_SECRET/);
  });

  it("throws a generic error on non-422 failures", async () => {
    (global.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => {
        throw new Error("not json");
      },
      text: async () => "internal error",
    });

    await expect(
      submitTicket(vi.fn().mockResolvedValue("tok"), {
        tenant_id: 1,
        ticket_title: "t",
        ticket_body: "b",
      }),
    ).rejects.toThrow(/500/);
  });

  it("forwards optional ticket_id and approval_token", async () => {
    (global.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({ job_id: 99 }),
    });

    await submitTicket(vi.fn().mockResolvedValue("tok"), {
      tenant_id: 1,
      ticket_title: "t",
      ticket_body: "b",
      ticket_id: "DEMO-7",
      approval_token: "raw-token",
    });

    const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>;
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.ticket_id).toBe("DEMO-7");
    expect(body.approval_token).toBe("raw-token");
  });

  it("forwards repo_id when provided (multi-repo per tenant)", async () => {
    (global.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({ job_id: 5 }),
    });

    await submitTicket(vi.fn().mockResolvedValue("tok"), {
      tenant_id: 1,
      repo_id: 7,
      ticket_title: "t",
      ticket_body: "b",
    });

    const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>;
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.tenant_id).toBe(1);
    expect(body.repo_id).toBe(7);
  });
});

describe("listMyTenants", () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  it("GETs /tenants/mine and returns the tenants array", async () => {
    (global.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        tenants: [
          { id: 1, name: "acme", github_owner: "acme", github_installation_id: 100, created_at: "", repos: [] },
        ],
      }),
    });

    const res = await listMyTenants(vi.fn().mockResolvedValue("jwt"));
    expect(res.tenants).toHaveLength(1);
    expect(res.tenants[0].github_owner).toBe("acme");

    const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>;
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/tenants\/mine$/);
    expect(init.headers.Authorization).toBe("Bearer jwt");
  });

  it("throws on non-200", async () => {
    (global.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 401,
      text: async () => "unauthorized",
    });

    await expect(
      listMyTenants(vi.fn().mockResolvedValue("jwt")),
    ).rejects.toThrow(/401/);
  });
});

describe("connectInstallation", () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  it("POSTs to /tenants/connect with installation_id + state", async () => {
    (global.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 7,
        name: "acme",
        github_owner: "acme",
        github_installation_id: 100,
        created_at: "",
        repos: [{ id: 11, full_name: "acme/api", default_branch: "main" }],
      }),
    });

    const res = await connectInstallation(vi.fn().mockResolvedValue("jwt"), {
      installation_id: 100,
      state: "abc12345",
    });
    expect(res.id).toBe(7);
    expect(res.repos).toHaveLength(1);

    const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>;
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/tenants\/connect$/);
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body);
    expect(body.installation_id).toBe(100);
    expect(body.state).toBe("abc12345");
  });

  it("throws on non-200", async () => {
    (global.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => ({ detail: "GitHub rejected installation_id=100: 404" }),
      text: async () => "",
    });

    await expect(
      connectInstallation(vi.fn().mockResolvedValue("jwt"), {
        installation_id: 100,
        state: "abc12345",
      }),
    ).rejects.toThrow(/502/);
  });
});

describe("mintApprovalAndRun", () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  it("POSTs to /approvals/run with Clerk JWT and returns job_id", async () => {
    (global.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({ token: "tok", command: "cmd", job_id: 7 }),
      text: async () => "",
    });

    const res = await mintApprovalAndRun(vi.fn().mockResolvedValue("jwt"), {
      command: "cmd",
      tenant_id: 1,
      ticket_title: "t",
      ticket_body: "b",
    });

    expect(res.job_id).toBe(7);
    const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>;
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/approvals\/run$/);
    expect(init.method).toBe("POST");
    expect(init.headers.Authorization).toBe("Bearer jwt");
  });

  it("throws when the backend returns non-200", async () => {
    (global.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 403,
      text: async () => "forbidden",
    });

    await expect(
      mintApprovalAndRun(vi.fn().mockResolvedValue("jwt"), {
        command: "cmd",
        tenant_id: 1,
        ticket_title: "t",
        ticket_body: "b",
      }),
    ).rejects.toThrow(/403/);
  });
});
