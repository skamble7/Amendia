import type { Signal } from "@/api/notificationsStream";

/**
 * Render a thin SSE signal as a human-readable activity line.
 *
 * These are the ONLY fields the notification-service currently pushes (see
 * `Signal` in notificationsStream.ts). The finer-grained "capability produced
 * <Artifact>" / "Checkpoint written #N" lines in the design mock are NOT derivable
 * from today's events — reaching that fidelity needs new runtime events
 * (`activity_executed`, `checkpoint_written`) plus a widened SSE payload. We
 * deliberately do not fabricate them.
 */
export function formatActivitySignal(sig: Signal): string {
  switch (sig.type) {
    case "hitl_task_created": {
      const what = sig.element_id ?? sig.task_id ?? "task";
      return sig.role ? `Task created — ${what} (waiting on ${sig.role})` : `Task created — ${what}`;
    }
    case "hitl_task_decided":
      return `Decision recorded — ${sig.element_id ?? sig.task_id ?? "task"}`;
    case "process_completed":
      return sig.outcome ? `Instance completed — ${sig.outcome}` : "Instance completed";
    case "process_failed":
      return "Instance failed";
    case "dispatch_accepted":
      return `Dispatched — ${sig.process_instance_id ?? "instance"}`;
    case "exception_raised":
      return `Exception raised — ${sig.exception_id ?? "—"}`;
    case "exception_dispatched":
      return `Exception dispatched — ${sig.exception_id ?? "—"}`;
    default:
      return sig.type;
  }
}
