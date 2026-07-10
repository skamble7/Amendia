import { describe, it, expect, vi, afterEach } from "vitest";
import { startNotificationsStream, type Signal } from "@/api/notificationsStream";
import { setTestToken, configureAuthBridge } from "@/auth/authToken";

/** A never-closing SSE body (like a real stream): enqueue frames, stay open. */
function sseBody(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const ch of chunks) controller.enqueue(enc.encode(ch));
    },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("startNotificationsStream", () => {
  it("delivers signals, ignores the ready frame and heartbeats, reports up", async () => {
    setTestToken("tok");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: sseBody([
        "event: ready\ndata: {}\n\n",
        'data: {"type":"hitl_task_created","task_id":"t1"}\n\n',
        ": ping\n\n",
      ]),
    });
    vi.stubGlobal("fetch", fetchMock);

    const signals: Signal[] = [];
    const statuses: string[] = [];
    const stop = startNotificationsStream({
      onSignal: (s) => signals.push(s),
      onStatus: (s) => statuses.push(s),
    });
    try {
      await vi.waitFor(() => expect(signals.length).toBe(1), { timeout: 2000 });
      expect(signals[0]).toEqual({ type: "hitl_task_created", task_id: "t1" });
      expect(statuses).toContain("up");
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/stream"),
        expect.objectContaining({
          headers: expect.objectContaining({ authorization: "Bearer tok" }),
        }),
      );
    } finally {
      stop();
    }
  });

  it("renews the token on a 401 response", async () => {
    const renew = vi.fn().mockResolvedValue("fresh");
    configureAuthBridge({ getToken: () => "stale", renew, onAuthLost: vi.fn() });

    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 401 });
    vi.stubGlobal("fetch", fetchMock);

    const stop = startNotificationsStream({ onSignal: () => {}, onStatus: () => {} });
    try {
      await vi.waitFor(() => expect(renew).toHaveBeenCalled(), { timeout: 2000 });
    } finally {
      stop();
    }
  });
});
