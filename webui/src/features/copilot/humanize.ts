// features/copilot/humanize.ts
// Generic, DOMAIN-NEUTRAL humanization for the business-facing copilot flow. Turns platform ids (role.*,
// Task_*, HITL modes) into plain-language labels and sentences — no domain vocabulary anywhere. The business
// user never sees a raw id, schema_ref, or HITL-mode string; all of that lives behind the technical inspection.
import { humanizeRole } from "@/lib/roles";
import type { HitlTaskMode } from "@/lib/hitl";
import type { OnboardingSession } from "@/api/services/registry";

// Strip a leading BPMN-ish prefix, split camelCase + underscores, sentence-case: "Task_FireTicket" → "Fire ticket".
const ID_PREFIX = /^(Task|Gateway|Start|End|Boundary|Event|Flow|Sub[Pp]rocess|Activity|Call)_/;
export function humanizeElementId(id: string): string {
  const spaced = id
    .replace(ID_PREFIX, "")
    .replace(/[._]+/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")   // camelCase → words
    .trim();
  if (!spaced) return id;
  const lower = spaced.toLowerCase();
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}

/** A role id → a person label ("role.x.manager" → "Manager"). Reuses the shared role humanizer. */
export function roleLabel(role: string | null | undefined): string {
  return role ? humanizeRole(role) : "Someone";
}

// mode → the verb for the "who acts here" sentence. approve_actions is the real-world-effect authorize gate.
const MODE_VERB: Record<HitlTaskMode, string> = {
  review_after: "reviews",
  approve_result: "approves",
  approve_actions: "authorizes",
  manual: "handles",
};
export function modeVerb(mode: string | null | undefined): string {
  return MODE_VERB[(mode ?? "manual") as HitlTaskMode] ?? "handles";
}

export interface Gate {
  elementId: string;
  sentence: string;
  /** true for approve_actions — a gate over a real-world side effect (badged "authorize"). */
  authorize: boolean;
}

/** The human-acts-here gates, derived generically from the bindings (each non-`none` HITL gate → a sentence). */
export function gatesOf(session: OnboardingSession): Gate[] {
  return (session.bindings ?? [])
    .filter((b) => b.hitl_mode && b.hitl_mode !== "none")
    .map((b) => {
      const who = roleLabel(b.hitl_role ?? b.role ?? null);
      const what = humanizeElementId(b.element_id).toLowerCase();
      return {
        elementId: b.element_id,
        sentence: `${who} ${modeVerb(b.hitl_mode)} ${what}.`,
        authorize: b.hitl_mode === "approve_actions",
      };
    });
}

export interface Readiness {
  ready: boolean;
  issues: string[];        // plain-language validator problems (empty when ready)
}

/** Validator status in business terms: clean + assembled → ready to go live; else the blocking problems. */
export function readinessOf(session: OnboardingSession): Readiness {
  const errors = (session.dry_run_report?.findings ?? []).filter((f) => f.severity === "error");
  return { ready: errors.length === 0 && session.state === "assembled", issues: errors.map((e) => e.message) };
}

// Swap platform jargon that can appear in a copilot reply (esp. clamp notices) for friendly phrasing, so the
// business user reads "kept … at authorize-level because it has a real-world effect", not raw HITL-mode strings.
const JARGON: [RegExp, string][] = [
  [/approve_actions/g, "authorize-level"],
  [/approve_result/g, "approval-level"],
  [/review_after/g, "review-level"],
  [/\bmanual\b/g, "hands-on"],
  [/the side-effect floor/g, "the required minimum for real-world actions"],
  [/side-effectful/g, "real-world-effect"],
  [/\bHITL\b/g, "oversight"],
  [/\bclamped\b/gi, "kept"],
];
export function friendlyReply(text: string): string {
  return JARGON.reduce((s, [re, to]) => s.replace(re, to), text);
}

/** A plain-language rendering of one ChangeDiff field ("hitl_role on Task_FireTicket" → "who approves…"). */
export function describeChangeField(field: string): string {
  switch (field) {
    case "hitl_mode": return "the level of oversight";
    case "hitl_role": return "who is responsible";
    case "capability_ref": return "which automated step runs";
    case "role": return "who does the work";
    case "output_name": return "what the step is called downstream";
    case "input_sources": return "where its information comes from";
    case "read_only_inputs": return "the context shown on the form";
    case "outputs": return "what the step produces";
    default: return field.replace(/_/g, " ");
  }
}
