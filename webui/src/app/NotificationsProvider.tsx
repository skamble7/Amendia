import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "react-oidc-context";
import { startNotificationsStream, type StreamStatus } from "@/api/notificationsStream";
import { LIVE_KEYS, signalToKeys } from "@/api/signalToKeys";

interface NotificationsValue {
  status: StreamStatus;
}

// Default "connecting" so any consumer rendered outside the provider (e.g. an
// isolated test) safely falls back to polling rather than assuming SSE is healthy.
const NotificationsContext = createContext<NotificationsValue>({ status: "connecting" });

/**
 * Owns the single SSE connection lifecycle. On each signal it invalidates the
 * mapped query keys (the data is re-fetched through the existing REST endpoints);
 * whenever the stream (re)connects it resyncs every live key to catch anything
 * missed while disconnected. Must render inside QueryClientProvider and under
 * AuthProvider (after AuthWiring configures the token bridge).
 */
export function NotificationsProvider({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<StreamStatus>("connecting");
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

  return <NotificationsContext.Provider value={{ status }}>{children}</NotificationsContext.Provider>;
}

/** The current SSE connection status — used by live.ts to pick a poll cadence. */
export function useNotificationsStatus(): StreamStatus {
  return useContext(NotificationsContext).status;
}
