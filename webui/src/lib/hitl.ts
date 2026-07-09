/**
 * HITL mode semantics — mirrors backend agent-runtime/app/engine/hitl.py:15-20
 * (ALLOWED_DECISIONS) and libs/amendia_contracts hitl_task.py. The UI renders
 * decision buttons strictly from a task's `allowed_decisions` array; this map is
 * a fallback/derivation and a source of the per-mode UI treatment, never a
 * replacement for the array the backend sends.
 */

export type HitlTaskMode = "review_after" | "approve_result" | "approve_actions" | "manual";

export type Decision =
  | "approve"
  | "reject"
  | "edit_and_approve"
  | "return_for_rework"
  | "complete"
  | "escalate";

export type TaskStatus = "open" | "claimed" | "decided" | "cancelled" | "expired";
export type TaskPriority = "low" | "normal" | "high" | "critical";

/** The four Task Detail variants keyed by mode (design Screen: Task Detail). */
export type TaskVariant = "review" | "approve_result" | "authorize_actions" | "manual";

interface ModeMeta {
  mode: HitlTaskMode;
  variant: TaskVariant;
  label: string;
  /** one-line business meaning (contracts_reference §2.4) */
  meaning: string;
  /** decisions the backend allows by default for this mode */
  allowedDecisions: Decision[];
}

export const HITL_MODE_META: Record<HitlTaskMode, ModeMeta> = {
  review_after: {
    mode: "review_after",
    variant: "review",
    label: "Review",
    meaning: "Agent output is a draft — you may correct it before it enters state.",
    allowedDecisions: ["approve", "edit_and_approve", "reject"],
  },
  approve_result: {
    mode: "approve_result",
    variant: "approve_result",
    label: "Approve result",
    meaning: "The result stands or falls as-is. No edits.",
    allowedDecisions: ["approve", "reject"],
  },
  approve_actions: {
    mode: "approve_actions",
    variant: "authorize_actions",
    label: "Authorize actions",
    meaning: "You authorize real-world side effects before they happen.",
    allowedDecisions: ["approve", "reject"],
  },
  manual: {
    mode: "manual",
    variant: "manual",
    label: "Manual",
    meaning: "This step is human work; the agent may pre-draft it.",
    allowedDecisions: ["complete", "escalate"],
  },
};

export const DECISION_META: Record<Decision, { label: string; tone: "success" | "danger" | "neutral" | "agent" }> = {
  approve: { label: "Approve", tone: "success" },
  edit_and_approve: { label: "Edit & approve", tone: "agent" },
  reject: { label: "Reject", tone: "danger" },
  return_for_rework: { label: "Return for rework", tone: "neutral" },
  complete: { label: "Complete", tone: "success" },
  escalate: { label: "Escalate", tone: "danger" },
};

export function modeMeta(mode: HitlTaskMode): ModeMeta {
  return HITL_MODE_META[mode];
}

/**
 * Resolve which decision buttons to render. The task's `allowed_decisions` is
 * authoritative; when absent (defensive) fall back to the mode default.
 */
export function decisionsForTask(task: {
  hitl_mode: HitlTaskMode;
  allowed_decisions?: Decision[] | null;
}): Decision[] {
  if (task.allowed_decisions && task.allowed_decisions.length > 0) {
    return task.allowed_decisions;
  }
  return HITL_MODE_META[task.hitl_mode].allowedDecisions;
}

/** Does deciding this task with `decision` require artifact edits in the payload? */
export function decisionNeedsEdits(decision: Decision): boolean {
  return decision === "edit_and_approve";
}
