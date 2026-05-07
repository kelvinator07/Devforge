/**
 * Unit tests for the network helpers in indexJobs.ts.
 * Mirrors the pattern used in api.test.ts (mocked global fetch, no React).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchIndexStatus, fetchIndexJob, startIndexJob } from "./indexJobs";

describe("fetchIndexStatus", () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  it("GETs /repos/:id/index-status with bearer token and returns parsed body", async () => {
    const body = {
      indexed: true,
      last_indexed_at: "2026-05-01T10:00:00Z",
      latest_job_id: 7,
      latest_status: "completed",
      files_indexed: 42,
      chunks_written: 130,
      error: null,
    };
    (global.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => body,
    });
    const getToken = vi.fn().mockResolvedValue("jwt-xyz");

    const res = await fetchIndexStatus(getToken, 99);
    expect(res).toEqual(body);

    const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>;
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/repos\/99\/index-status$/);
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer jwt-xyz",
    });
  });

  it("throws on non-OK response", async () => {
    (global.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 404,
      text: async () => "not found",
    });
    const getToken = vi.fn().mockResolvedValue(null);
    await expect(fetchIndexStatus(getToken, 1)).rejects.toThrow(/index-status failed: 404/);
  });
});

describe("startIndexJob", () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  it("POSTs to /repos/:id/index and returns the job id", async () => {
    (global.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({ index_job_id: 13, already_running: false }),
    });
    const getToken = vi.fn().mockResolvedValue("jwt");

    const res = await startIndexJob(getToken, 5);
    expect(res).toEqual({ index_job_id: 13, already_running: false });

    const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>;
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/repos\/5\/index$/);
    expect((init as RequestInit).method).toBe("POST");
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer jwt",
      "Content-Type": "application/json",
    });
  });

  it("returns already_running=true when an index job is already in flight", async () => {
    (global.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({ index_job_id: 4, already_running: true }),
    });
    const getToken = vi.fn().mockResolvedValue("jwt");

    const res = await startIndexJob(getToken, 5);
    expect(res.already_running).toBe(true);
    expect(res.index_job_id).toBe(4);
  });
});

describe("fetchIndexJob", () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  it("returns snapshot with job + events", async () => {
    const snapshot = {
      job: {
        id: 1,
        tenant_id: 2,
        repo_id: 3,
        status: "running",
        files_indexed: null,
        chunks_written: null,
        error: null,
        created_at: "2026-05-07T00:00:00Z",
        started_at: "2026-05-07T00:00:01Z",
        finished_at: null,
      },
      events: [
        { id: 1, event: "index_started", payload: "{}", ts: "2026-05-07T00:00:01Z" },
      ],
    };
    (global.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => snapshot,
    });
    const res = await fetchIndexJob(vi.fn().mockResolvedValue("t"), 1);
    expect(res).toEqual(snapshot);
  });
});
