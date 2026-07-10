import {
  useQuery,
  type QueryKey,
  type UseQueryOptions,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useNotificationsStatus } from "@/app/NotificationsProvider";
import type { StreamStatus } from "@/api/notificationsStream";

/**
 * The "liveness" seam — the ONE place the update transport lives. Real-time updates
 * arrive via the notification-service SSE stream, which invalidates the same query
 * keys features already use (see NotificationsProvider + signalToKeys). Polling is
 * now only a **fallback**:
 *   - SSE healthy  → a slow safety refetch (SSE drives freshness).
 *   - SSE down     → a fast poll so the app still updates if the stream is gone.
 * Features call usePollingQuery and never learn which transport is underneath.
 */

/** Slow safety refetch while the SSE stream is healthy (SSE does the real work). */
export const SSE_HEALTHY_POLL_MS = 60_000;
/** Fast fallback poll when the SSE stream is down/connecting. */
export const FALLBACK_POLL_MS = 5_000;

/**
 * Effective refetch cadence from SSE health + the caller's fallback interval:
 *   one-shot (`false`) stays one-shot; SSE up → slow safety poll; SSE down →
 *   the caller's fast cadence (or FALLBACK_POLL_MS).
 */
export function pollInterval(
  status: StreamStatus,
  intervalMs: number | false | undefined,
): number | false {
  if (intervalMs === false) return false;
  if (status === "up") return SSE_HEALTHY_POLL_MS;
  return intervalMs ?? FALLBACK_POLL_MS;
}

export interface LiveQueryOptions<T> {
  queryKey: QueryKey;
  queryFn: (signal: AbortSignal) => Promise<T>;
  /** fallback poll cadence when SSE is down; defaults to FALLBACK_POLL_MS. Pass
   *  false to fetch once (no polling, ever). */
  intervalMs?: number | false;
  enabled?: boolean;
  staleTime?: number;
}

export function usePollingQuery<T>(opts: LiveQueryOptions<T>): UseQueryResult<T> {
  const { queryKey, queryFn, intervalMs, enabled = true, staleTime } = opts;
  const sseStatus = useNotificationsStatus();
  const refetchInterval = pollInterval(sseStatus, intervalMs);

  const options: UseQueryOptions<T, Error, T, QueryKey> = {
    queryKey,
    queryFn: ({ signal }) => queryFn(signal),
    refetchInterval,
    refetchIntervalInBackground: false,
    enabled,
    staleTime,
  };
  return useQuery(options);
}

/** One-shot fetch (no polling) for detail views that don't need live updates.
 *  These still refresh in real time because SSE invalidates their query keys. */
export function useApiQuery<T>(
  queryKey: QueryKey,
  queryFn: (signal: AbortSignal) => Promise<T>,
  opts: { enabled?: boolean; staleTime?: number } = {},
): UseQueryResult<T> {
  return useQuery({
    queryKey,
    queryFn: ({ signal }) => queryFn(signal),
    enabled: opts.enabled ?? true,
    staleTime: opts.staleTime,
  });
}
