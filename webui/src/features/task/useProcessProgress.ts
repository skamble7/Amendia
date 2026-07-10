import { useApiQuery } from "@/api/live";
import { getPack } from "@/api/services/registry";
import { getInstance } from "@/api/services/runtime";
import { deriveSteps, type Step } from "@/lib/steps";
import type { HitlTask, ProcessPackManifest, InstanceDetail } from "@/api/types";

/**
 * Shared derivation of the live process position for a task, used by both the
 * context rail's step tracker and the full BPMN process diagram. The current step
 * comes from the *instance's* open/claimed gate (not the task being viewed), so it
 * advances in real time as the process moves on (SSE invalidates ["instance", id]).
 */
export function useProcessProgress(task: HitlTask): {
  pack: ProcessPackManifest | undefined;
  instance: InstanceDetail | undefined;
  steps: Step[];
} {
  const { data: pack } = useApiQuery(
    ["pack", task.pack_key, task.pack_version],
    (s) => getPack(task.pack_key, task.pack_version, s),
    { staleTime: Infinity },
  );
  const { data: instance } = useApiQuery(["instance", task.process_instance_id], (s) =>
    getInstance(task.process_instance_id, s),
  );

  const terminal = instance ? ["completed", "failed", "cancelled"].includes(instance.status) : false;
  const currentEl = instance?.hitl_tasks.find((t) => t.status === "open" || t.status === "claimed")?.element_id;
  const failedEl =
    instance?.status === "failed" ? instance.actor_log[instance.actor_log.length - 1]?.element_id : null;
  const steps = deriveSteps(pack, instance?.actor_log, {
    currentElementId: currentEl,
    failedElementId: failedEl,
    terminal,
  });

  return { pack, instance, steps };
}
