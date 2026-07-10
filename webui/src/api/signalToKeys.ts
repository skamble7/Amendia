import type { QueryKey } from "@tanstack/react-query";
import type { Signal } from "./notificationsStream";

/**
 * Every "live" query key. Invalidated wholesale on (re)connect and on a `resync`
 * signal, so anything missed while the stream was down is caught. List keys are
 * prefixes — invalidating `["instances"]` matches every `["instances", filters]`.
 */
export const LIVE_KEYS: QueryKey[] = [
  ["hitl-tasks"],
  ["hitl-task"],
  ["instances"],
  ["instance"],
  ["ingestions"],
  ["ingestion"],
  ["exceptions"],
  ["exception"],
  ["me"],
];

/**
 * Map a thin signal → the TanStack Query keys to invalidate. Prefix keys hit all
 * filter variants; id-scoped keys refresh the specific entity. The browser then
 * re-fetches through the existing role-guarded REST endpoints.
 */
export function signalToKeys(signal: Signal): QueryKey[] {
  const pid = signal.process_instance_id;
  const eid = signal.exception_id;
  const tid = signal.task_id;

  switch (signal.type) {
    case "resync":
      return LIVE_KEYS;

    case "hitl_task_created":
    case "hitl_task_decided": {
      const keys: QueryKey[] = [["hitl-tasks"], ["instances"]];
      if (tid) keys.push(["hitl-task", tid]);
      if (pid) keys.push(["instance", pid]);
      if (eid) keys.push(["exception", eid], ["ingestion", eid]);
      return keys;
    }

    case "process_completed":
    case "process_failed": {
      const keys: QueryKey[] = [["hitl-tasks"], ["instances"]];
      if (pid) keys.push(["instance", pid]);
      if (eid) keys.push(["exception", eid]);
      return keys;
    }

    case "dispatch_accepted": {
      const keys: QueryKey[] = [["instances"], ["ingestions"]];
      if (pid) keys.push(["instance", pid]);
      if (eid) keys.push(["ingestion", eid]);
      return keys;
    }

    case "exception_raised":
    case "exception_dispatched": {
      // `["exceptions"]` (list) feeds the dashboard's Raised counter + reason-code
      // tally; the id-scoped `["exception", eid]` refreshes the detail view.
      const keys: QueryKey[] = [["exceptions"], ["ingestions"], ["instances"]];
      if (eid) keys.push(["exception", eid], ["ingestion", eid]);
      return keys;
    }

    default:
      return [];
  }
}
