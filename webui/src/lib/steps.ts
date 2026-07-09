import type { ProcessPackManifest, ActorLogEntry } from "@/api/types";
import { humanizeKey } from "@/components/artifact/schema";

export interface Step {
  element_id: string;
  label: string;
  kind: "serviceTask" | "userTask" | string;
  hitl_mode?: string | null;
  state: "done" | "current" | "pending" | "failed";
}

/** Human label for a BPMN element id (Task_AssessRepairability → "Assess repairability"). */
export function elementLabel(elementId: string): string {
  return humanizeKey(elementId.replace(/^Task_/, "").replace(/^Gateway_/, ""));
}

/**
 * Derive the horizontal step sequence from the pack manifest bindings order
 * (the authoritative execution order the platform runs), marking each step done /
 * current / pending from the instance actor_log and the currently-open element.
 * The BPMN diagram may show a parallel fork/join, but the executed pack is
 * linearized — so this tracker is a linear chain by design.
 */
export function deriveSteps(
  pack: ProcessPackManifest | undefined,
  actorLog: ActorLogEntry[] | undefined,
  opts: { currentElementId?: string | null; failedElementId?: string | null; terminal?: boolean } = {},
): Step[] {
  if (!pack?.bindings) return [];
  const acted = new Set((actorLog ?? []).map((e) => e.element_id));
  const { currentElementId, failedElementId, terminal } = opts;

  return pack.bindings.map((b) => {
    const element_id = b.element_id;
    let state: Step["state"] = "pending";
    if (failedElementId && element_id === failedElementId) state = "failed";
    else if (currentElementId && element_id === currentElementId) state = "current";
    else if (acted.has(element_id)) state = "done";
    else if (terminal) state = "done"; // completed instance: everything reached is done
    return {
      element_id,
      label: elementLabel(element_id),
      kind: b.element_kind,
      hitl_mode: b.hitl?.mode ?? null,
      state,
    };
  });
}
