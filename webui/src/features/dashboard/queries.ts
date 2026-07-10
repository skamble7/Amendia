import { usePollingQuery } from "@/api/live";
import { listExceptions } from "@/api/services/stub";
import { listIngestions } from "@/api/services/ingestor";
import { listInstances, listHitlTasks } from "@/api/services/runtime";

/**
 * Dashboard data hooks — thin wrappers over the EXISTING list services, fetched
 * through the live seam (usePollingQuery) so the notification-service SSE stream
 * keeps them fresh via the shared query keys. All aggregation is client-side (see
 * ./compute); there is no dashboard-specific backend endpoint.
 *
 * We cap each list at 200 recent records; the page surfaces a "showing recent N"
 * hint when a list hits the cap so counters never silently under-report.
 */
export const DASHBOARD_LIMIT = 200;

/** Exceptions — Raised counter + reason-code tally. */
export function useDashboardExceptions() {
  return usePollingQuery({
    queryKey: ["exceptions", { limit: DASHBOARD_LIMIT }],
    queryFn: (signal) => listExceptions({ limit: DASHBOARD_LIMIT }, signal),
  });
}

/** Ingestions — Ingested / Dispatched counters. */
export function useDashboardIngestions() {
  return usePollingQuery({
    queryKey: ["ingestions", { limit: DASHBOARD_LIMIT }],
    queryFn: (signal) => listIngestions({ limit: DASHBOARD_LIMIT }, signal),
  });
}

/** Instances — Running / Waiting / Completed / Failed counters. */
export function useDashboardInstances() {
  return usePollingQuery({
    queryKey: ["instances", { limit: DASHBOARD_LIMIT }],
    queryFn: (signal) => listInstances({ limit: DASHBOARD_LIMIT }, signal),
  });
}

/** Failed instances — Needs-triage list (authoritative, not day-scoped). */
export function useFailedInstances() {
  return usePollingQuery({
    queryKey: ["instances", { status: "failed", limit: DASHBOARD_LIMIT }],
    queryFn: (signal) => listInstances({ status: "failed", limit: DASHBOARD_LIMIT }, signal),
  });
}

/** No-process ingestions — Needs-triage list. */
export function useNoProcessIngestions() {
  return usePollingQuery({
    queryKey: ["ingestions", { status: "no_process", limit: DASHBOARD_LIMIT }],
    queryFn: (signal) => listIngestions({ status: "no_process", limit: DASHBOARD_LIMIT }, signal),
  });
}

/** Open HITL tasks — Waiting-on-human queue. */
export function useOpenTasks() {
  return usePollingQuery({
    queryKey: ["hitl-tasks", { status: "open", limit: DASHBOARD_LIMIT }],
    queryFn: (signal) => listHitlTasks({ status: "open", limit: DASHBOARD_LIMIT }, signal),
  });
}
