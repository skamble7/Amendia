import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Signal, StreamStatus } from "@/api/notificationsStream";
import { LIVE_KEYS } from "@/api/signalToKeys";

// Capture the callbacks the provider hands to the (mocked) stream so the test can
// drive signals/status directly, without a real SSE connection.
let captured: { onSignal: (s: Signal) => void; onStatus: (s: StreamStatus) => void } | null = null;
const stopFn = vi.fn();

vi.mock("@/api/notificationsStream", () => ({
  startNotificationsStream: (opts: { onSignal: (s: Signal) => void; onStatus: (s: StreamStatus) => void }) => {
    captured = opts;
    return stopFn;
  },
}));

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ isAuthenticated: true }),
}));

import { NotificationsProvider } from "@/app/NotificationsProvider";

function renderProvider() {
  const qc = new QueryClient();
  const spy = vi.spyOn(qc, "invalidateQueries");
  render(
    <QueryClientProvider client={qc}>
      <NotificationsProvider>
        <div>child</div>
      </NotificationsProvider>
    </QueryClientProvider>,
  );
  return spy;
}

describe("NotificationsProvider", () => {
  beforeEach(() => {
    captured = null;
    stopFn.mockClear();
  });

  it("invalidates the mapped query keys when a signal arrives", async () => {
    const spy = renderProvider();
    await waitFor(() => expect(captured).not.toBeNull());

    spy.mockClear();
    captured!.onSignal({ type: "hitl_task_created", task_id: "t1", process_instance_id: "pi1" });

    expect(spy).toHaveBeenCalledWith({ queryKey: ["hitl-tasks"] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["hitl-task", "t1"] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["instance", "pi1"] });
  });

  it("resyncs every live key when the stream (re)connects", async () => {
    const spy = renderProvider();
    await waitFor(() => expect(captured).not.toBeNull());

    spy.mockClear();
    captured!.onStatus("up");

    for (const key of LIVE_KEYS) {
      expect(spy).toHaveBeenCalledWith({ queryKey: key });
    }
  });
});
