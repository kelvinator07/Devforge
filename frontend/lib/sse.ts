/**
 * SSE wrapper using @microsoft/fetch-event-source so we can attach the
 * Clerk JWT in Authorization (browser-native EventSource can't set headers).
 */
import { fetchEventSource } from "@microsoft/fetch-event-source";

import { API } from "./api";

export type IncomingEvent = {
  id: number;
  type: string;
  data: Record<string, unknown>;
};

export function tailJob(opts: {
  jobId: number;
  getToken: () => Promise<string | null>;
  onEvent: (e: IncomingEvent) => void;
  onClose?: () => void;
  onError?: (err: unknown) => void;
}): () => void {
  const ctrl = new AbortController();
  (async () => {
    const tok = await opts.getToken();
    const headers: Record<string, string> = { Accept: "text/event-stream" };
    if (tok) headers["Authorization"] = `Bearer ${tok}`;

    try {
      await fetchEventSource(`${API}/jobs/${opts.jobId}/sse`, {
        headers,
        signal: ctrl.signal,
        openWhenHidden: true,
        onmessage(msg) {
          let data: Record<string, unknown> = {};
          try {
            data = JSON.parse(msg.data || "{}");
          } catch { /* ignore parse errors */ }
          opts.onEvent({
            id: Number(msg.id) || 0,
            type: msg.event || "message",
            data,
          });
        },
        onclose() {
          opts.onClose?.();
        },
        onerror(err) {
          opts.onError?.(err);
          // Returning `undefined` lets the library retry; throwing stops it.
          throw err;
        },
      });
    } catch (err) {
      // Aborted on unmount is expected.
      if ((err as Error)?.name === "AbortError") return;
      opts.onError?.(err);
    }
  })();
  return () => ctrl.abort();
}
