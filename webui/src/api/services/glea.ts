import { request } from "../client";
import type {
  DecisionTrailOut,
  InstanceAuditOut,
  LineageOut,
  MetricsBundle,
  TraceTreeOut,
} from "../types";

/**
 * glea-service read-models (ADR-058 Phase E). glea is OPTIONAL at the UI layer: telemetry/audit may
 * not be deployed, or an old instance may have no data. Every call degrades to `null` on a connectivity
 * failure (status 0), a missing service (404), or an unavailable store (503) — the instance page then
 * renders the core agent-runtime view and shows an "unavailable / no data" state for the GLEA sections,
 * never a crash. Mirrors the runtime `getInstanceState` null-on-404/503 pattern.
 */
async function optional<T>(fn: () => Promise<T>): Promise<T | null> {
  try {
    return await fn();
  } catch (err) {
    const status = (err as { status?: number }).status;
    if (status === 0 || status === 404 || status === 503) return null;
    throw err;
  }
}

export function getInstanceAudit(cid: string, signal?: AbortSignal): Promise<InstanceAuditOut | null> {
  return optional(() =>
    request<InstanceAuditOut>("glea", `/audit/instances/${cid}`, { signal, silent: true }),
  );
}

export function getDecisionTrail(cid: string, signal?: AbortSignal): Promise<DecisionTrailOut | null> {
  return optional(() =>
    request<DecisionTrailOut>("glea", `/audit/instances/${cid}/decision-trail`, { signal, silent: true }),
  );
}

export function getLineage(cid: string, signal?: AbortSignal): Promise<LineageOut | null> {
  return optional(() =>
    request<LineageOut>("glea", `/audit/instances/${cid}/lineage`, { signal, silent: true }),
  );
}

export function getInstanceMetrics(cid: string, signal?: AbortSignal): Promise<MetricsBundle | null> {
  return optional(() =>
    request<MetricsBundle>("glea", `/audit/instances/${cid}/metrics`, { signal, silent: true }),
  );
}

export function getTraceTree(cid: string, signal?: AbortSignal): Promise<TraceTreeOut | null> {
  return optional(() =>
    request<TraceTreeOut>("glea", `/audit/instances/${cid}/trace`, { signal, silent: true }),
  );
}
