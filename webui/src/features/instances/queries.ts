import { usePollingQuery, useApiQuery } from "@/api/live";
import { listInstances, getInstance, getInstanceState, type InstanceFilters } from "@/api/services/runtime";
import { getPack } from "@/api/services/registry";

export function useInstances(filters: InstanceFilters = {}) {
  return usePollingQuery({
    queryKey: ["instances", filters],
    queryFn: (signal) => listInstances(filters, signal),
  });
}

export function useInstance(id: string | undefined) {
  return usePollingQuery({
    queryKey: ["instance", id],
    queryFn: (signal) => getInstance(id!, signal),
    enabled: !!id,
    intervalMs: 5000,
  });
}

/** Flag-guarded checkpointed state (artifacts). Null when the debug flag is off. */
export function useInstanceState(id: string | undefined) {
  return useApiQuery(["instance-state", id], (signal) => getInstanceState(id!, signal), { enabled: !!id });
}

export function usePack(packKey: string | undefined, version: string | undefined) {
  return useApiQuery(["pack", packKey, version], (signal) => getPack(packKey!, version!, signal), {
    enabled: !!packKey && !!version,
    staleTime: Infinity,
  });
}
