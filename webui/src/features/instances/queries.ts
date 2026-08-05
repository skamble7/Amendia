import { usePollingQuery, useApiQuery } from "@/api/live";
import { listInstances, getInstance, getInstanceState, type InstanceFilters } from "@/api/services/runtime";
import { getPack } from "@/api/services/registry";
import {
  getDecisionTrail,
  getInstanceAudit,
  getInstanceMetrics,
  getLineage,
  getTraceTree,
} from "@/api/services/glea";

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

// --- GLEA read-models (ADR-058 Phase E). Keyed by correlation_id; each degrades to null when glea
// is unreachable/not deployed, so the page still renders the core agent-runtime view. ---
export function useDecisionTrail(cid: string | undefined) {
  return useApiQuery(["glea-decision-trail", cid], (s) => getDecisionTrail(cid!, s), { enabled: !!cid });
}
export function useLineage(cid: string | undefined) {
  return useApiQuery(["glea-lineage", cid], (s) => getLineage(cid!, s), { enabled: !!cid });
}
export function useInstanceAudit(cid: string | undefined) {
  return useApiQuery(["glea-audit", cid], (s) => getInstanceAudit(cid!, s), { enabled: !!cid });
}
export function useInstanceMetrics(cid: string | undefined) {
  return useApiQuery(["glea-metrics", cid], (s) => getInstanceMetrics(cid!, s), { enabled: !!cid });
}
export function useTraceTree(cid: string | undefined) {
  return useApiQuery(["glea-trace", cid], (s) => getTraceTree(cid!, s), { enabled: !!cid });
}
