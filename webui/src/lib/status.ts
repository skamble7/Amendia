import type { BadgeProps } from "@/components/ui/badge";

type Variant = NonNullable<BadgeProps["variant"]>;

/** Instance statuses: created, running, waiting_hitl, waiting_timer (ADR-029),
 * waiting_message (ADR-031), completed, failed, cancelled. */
export const INSTANCE_STATUS: Record<string, { label: string; variant: Variant }> = {
  created: { label: "Created", variant: "outline" },
  running: { label: "Running", variant: "agent" },
  waiting_hitl: { label: "Waiting on human", variant: "attention" },
  waiting_timer: { label: "Waiting on timer", variant: "process" },
  waiting_message: { label: "Waiting for message", variant: "process" },
  completed: { label: "Completed", variant: "success" },
  failed: { label: "Failed", variant: "danger" },
  cancelled: { label: "Cancelled", variant: "default" },
};

/** Ingestion lifecycle: received, dispatched, accepted, rejected, no_process. */
export const INGESTION_STATUS: Record<string, { label: string; variant: Variant }> = {
  received: { label: "Received", variant: "outline" },
  dispatched: { label: "Dispatched", variant: "process" },
  accepted: { label: "Accepted", variant: "agent" },
  rejected: { label: "Rejected", variant: "danger" },
  no_process: { label: "No process", variant: "danger" },
};

/** HITL task statuses: open, claimed, decided, cancelled, expired. */
export const TASK_STATUS: Record<string, { label: string; variant: Variant }> = {
  open: { label: "Open", variant: "attention" },
  claimed: { label: "Claimed", variant: "agent" },
  decided: { label: "Decided", variant: "success" },
  cancelled: { label: "Cancelled", variant: "default" },
  expired: { label: "Expired", variant: "danger" },
};

export const TASK_PRIORITY: Record<string, { label: string; variant: Variant }> = {
  low: { label: "Low", variant: "outline" },
  normal: { label: "Normal", variant: "default" },
  high: { label: "High", variant: "attention" },
  critical: { label: "Critical", variant: "danger" },
};

/** Registry lifecycle: draft, validated, active, deprecated. */
export const REGISTRY_STATUS: Record<string, { label: string; variant: Variant }> = {
  draft: { label: "Draft", variant: "outline" },
  validated: { label: "Validated", variant: "artifact" },
  active: { label: "Active", variant: "success" },
  deprecated: { label: "Deprecated", variant: "default" },
};

export function statusMeta(
  map: Record<string, { label: string; variant: Variant }>,
  key: string | null | undefined,
): { label: string; variant: Variant } {
  if (!key) return { label: "—", variant: "outline" };
  return map[key] ?? { label: key, variant: "outline" };
}
