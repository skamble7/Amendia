import { NOTIFICATIONS_BASE } from "./config";
import { authBridge } from "@/auth/authToken";

/** Connection health of the SSE stream (drives the polling fallback in live.ts). */
export type StreamStatus = "connecting" | "up" | "down";

/** A thin invalidation signal pushed from the notification-service. */
export interface Signal {
  type: string;
  exception_id?: string;
  process_instance_id?: string;
  task_id?: string;
  element_id?: string;
  role?: string;
  outcome?: string;
}

interface Opts {
  onSignal: (signal: Signal) => void;
  onStatus: (status: StreamStatus) => void;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Open a long-lived SSE stream to the notification-service and deliver thin
 * invalidation signals. Uses `fetch` (native EventSource can't send an
 * Authorization header) so it reuses the OIDC token bridge and mirrors the API
 * client's `401 → renew → retry` cycle. Auto-reconnects with capped exponential
 * backoff. Returns a stop function.
 */
export function startNotificationsStream({ onSignal, onStatus }: Opts): () => void {
  let stopped = false;
  let controller: AbortController | null = null;
  let attempt = 0;

  async function connectOnce(): Promise<void> {
    const token = authBridge.token();
    if (!token) {
      onStatus("down");
      return; // not authenticated yet — the loop retries
    }
    controller = new AbortController();
    onStatus("connecting");

    let res: Response;
    try {
      res = await fetch(`${NOTIFICATIONS_BASE}/stream`, {
        headers: { authorization: `Bearer ${token}`, accept: "text/event-stream" },
        signal: controller.signal,
        cache: "no-store",
      });
    } catch {
      onStatus("down"); // network error / abort
      return;
    }

    if (res.status === 401) {
      const renewed = await authBridge.renew();
      if (!renewed) authBridge.onAuthLost();
      onStatus("down");
      return; // reconnect with the fresh token (or after sign-in)
    }
    if (!res.ok || !res.body) {
      onStatus("down");
      return;
    }

    attempt = 0; // healthy connection resets backoff
    onStatus("up");

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (!stopped) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx: number;
        // SSE frames are separated by a blank line.
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
          handleFrame(buffer.slice(0, idx));
          buffer = buffer.slice(idx + 2);
        }
      }
    } catch {
      // aborted or dropped — fall through to reconnect
    } finally {
      onStatus("down");
    }
  }

  function handleFrame(frame: string): void {
    // Keep only `data:` lines; ignore `:` heartbeats and `event:`/`id:` lines.
    const data = frame
      .split("\n")
      .filter((l) => l.startsWith("data:"))
      .map((l) => l.slice(5).trim())
      .join("\n");
    if (!data || data === "{}") return; // the `ready` frame carries no signal
    try {
      const sig = JSON.parse(data) as Signal;
      if (sig && typeof sig.type === "string") onSignal(sig);
    } catch {
      /* ignore malformed frame */
    }
  }

  (async () => {
    while (!stopped) {
      await connectOnce();
      if (stopped) break;
      attempt += 1;
      const backoff = Math.min(30000, 1000 * 2 ** Math.min(attempt, 5)) + Math.random() * 500;
      await sleep(backoff);
    }
  })();

  return () => {
    stopped = true;
    controller?.abort();
    onStatus("down");
  };
}
