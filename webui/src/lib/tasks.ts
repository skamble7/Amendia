import type { HitlTask } from "@/api/types";
import { roleLabel } from "@/lib/roles";

export { roleLabel };

export interface TaskEligibility {
  /** current user may claim/decide this task */
  canAct: boolean;
  /** locked specifically by separation of duties (vs. plain role mismatch) */
  sodLocked: boolean;
  /** human-readable lock reason for the tooltip, or null when actionable */
  reason: string | null;
}

/**
 * Whether the current user can act on a task, and why not. Mirrors the runtime's
 * claim/decide guards, keyed off the caller's Amendia identity: the task's role
 * must be among the user's roles, and their `amendia_user_id` must not be in
 * sod.excluded_users. The SoD reason comes from sod.derived_from (human-readable
 * strings the runtime populates — render them verbatim).
 */
export function taskEligibility(task: HitlTask, amendiaUserId: string, roles: string[]): TaskEligibility {
  const excluded = task.sod?.excluded_users?.includes(amendiaUserId) ?? false;
  if (excluded) {
    const reason = task.sod?.derived_from?.length
      ? task.sod.derived_from.join("; ")
      : "Separation of duties: you already acted on a conflicting step.";
    return { canAct: false, sodLocked: true, reason };
  }
  if (task.role && !roles.includes(task.role)) {
    return { canAct: false, sodLocked: false, reason: `Requires the ${roleLabel(task.role)} role` };
  }
  if (task.status !== "open" && task.status !== "claimed") {
    return { canAct: false, sodLocked: false, reason: `Task is ${task.status}` };
  }
  return { canAct: true, sodLocked: false, reason: null };
}
