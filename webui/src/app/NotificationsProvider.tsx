import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "react-oidc-context";
import { startNotificationsStream, type Signal, type StreamStatus } from "@/api/notificationsStream";
import { LIVE_KEYS, signalToKeys } from "@/api/signalToKeys";

/** A received SSE signal stamped with the client's receive time (rendered by the
 *  dashboard's live-activity feed). `id` is a stable per-session key for React. */
export interface ActivityEntry {
  id: number;
  signal: Signal;
  receivedAt: string;
}

/** How many recent signals the dashboard feed keeps in memory. */
const ACTIVITY_LIMIT = 30;

interface NotificationsValue {
  status: StreamStatus;
  /** Rolling buffer of the most recent signals, newest first. */
  activity: ActivityEntry[];
  /** Count of meaningful signals received this session (drives the header pill). */
  eventCount: number;
}

// Default "connecting" so any consumer rendered outside the provider (e.g. an
// isolated test) safely falls back to polling rather than assuming SSE is healthy,
// and sees an empty activity buffer rather than crashing.
const NotificationsContext = createContext<NotificationsValue>({
  status: "connecting",
  activity: [],
  eventCount: 0,
});

/**
 * Owns the single SSE connection lifecycle. On each signal it invalidates the
 * mapped query keys (the data is re-fetched through the existing REST endpoints);
 * whenever the stream (re)connects it resyncs every live key to catch anything
 * missed while disconnected. It also keeps a rolling buffer of recent signals and
 * a session event counter for the dashboard's live-activity feed / header pill.
 * Must render inside QueryClientProvider and under AuthProvider (after AuthWiring
 * configures the token bridge).
 */
export function NotificationsProvider({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const [activity, setActivity] = useState<ActivityEntry[]>([]);
  const [eventCount, setEventCount] = useState(0);
  const nextId = useRef(0);
  const authed = auth.isAuthenticated;

  useEffect(() => {
    if (!authed) {
      setStatus("down");
      return;
    }
    const stop = startNotificationsStream({
      onSignal: (signal) => {
        for (const key of signalToKeys(signal)) {
          queryClient.invalidateQueries({ queryKey: key });
        }
        // `resync` is connection housekeeping, not a domain event — don't surface it.
        if (signal.type === "resync") return;
        setEventCount((c) => c + 1);
        setActivity((prev) => {
          const entry: ActivityEntry = {
            id: nextId.current++,
            signal,
            receivedAt: new Date().toISOString(),
          };
          return [entry, ...prev].slice(0, ACTIVITY_LIMIT);
        });
      },
      onStatus: (next) => {
        setStatus(next);
        if (next === "up") {
          // Resync everything possibly missed while disconnected.
          for (const key of LIVE_KEYS) queryClient.invalidateQueries({ queryKey: key });
        }
      },
    });
    return stop;
  }, [authed, queryClient]);

  return (
    <NotificationsContext.Provider value={{ status, activity, eventCount }}>
      {children}
    </NotificationsContext.Provider>
  );
}

/** The current SSE connection status — used by live.ts to pick a poll cadence. */
export function useNotificationsStatus(): StreamStatus {
  return useContext(NotificationsContext).status;
}

/** Rolling buffer of recent SSE signals, newest first (dashboard live-activity feed). */
export function useRecentActivity(): ActivityEntry[] {
  return useContext(NotificationsContext).activity;
}

/** Number of meaningful signals received this session (dashboard header pill). */
export function useSessionEventCount(): number {
  return useContext(NotificationsContext).eventCount;
}
