import {
  useQuery,
  type QueryKey,
  type UseQueryOptions,
  type UseQueryResult,
} from "@tanstack/react-query";
import { LIVE_POLL_MS } from "@/app/providers";

/**
 * The "liveness" seam. Today every live surface (inbox, instance status, activity
 * feed) polls via TanStack Query's refetchInterval. When the notification service's
 * SSE fan-out ships, only this module changes — swap the interval for an
 * EventSource subscription that invalidates the same query keys. Features call
 * usePollingQuery and never learn which transport is underneath.
 */
export interface LiveQueryOptions<T> {
  queryKey: QueryKey;
  queryFn: (signal: AbortSignal) => Promise<T>;
  /** poll cadence; defaults to LIVE_POLL_MS. Pass false to fetch once (no polling). */
  intervalMs?: number | false;
  enabled?: boolean;
  staleTime?: number;
}

export function usePollingQuery<T>(opts: LiveQueryOptions<T>): UseQueryResult<T> {
  const { queryKey, queryFn, intervalMs = LIVE_POLL_MS, enabled = true, staleTime } = opts;
  const options: UseQueryOptions<T, Error, T, QueryKey> = {
    queryKey,
    queryFn: ({ signal }) => queryFn(signal),
    refetchInterval: intervalMs === false ? false : intervalMs,
    refetchIntervalInBackground: false,
    enabled,
    staleTime,
  };
  return useQuery(options);
}

/** One-shot fetch (no polling) for detail views that don't need live updates. */
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
