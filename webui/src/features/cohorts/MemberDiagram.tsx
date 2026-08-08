import { Link } from "react-router-dom";
import { ArrowUpRight } from "lucide-react";
import { BpmnViewer, type BpmnMarker } from "@/features/registry/BpmnViewer";
import { usePackBpmn } from "@/features/registry/queries";
import { useInstance, usePack } from "@/features/instances/queries";
import { deriveSteps } from "@/lib/steps";
import { IdMono } from "@/components/primitives";
import { MemberStatusChip } from "./cohortBits";
import type { CohortRosterMember } from "@/api/types";

/**
 * One roster member rendered as its own BPMN diagram with LIVE per-member execution highlighting — the exact
 * instance-view path (deriveSteps → BpmnMarker[] → BpmnViewer). A running member shows its current node,
 * un-taken branches stay pending, a failed member reddens the failed node (ADR-062 precision, per member).
 * Degrades gracefully: if the pack BPMN or the instance is unavailable, the roster header still renders.
 */
export function MemberDiagram({ member }: { member: CohortRosterMember }) {
  const { data: pack } = usePack(member.pack_key, member.pack_version);
  const { data: bpmn } = usePackBpmn(member.pack_key, member.pack_version);
  const { data: instance } = useInstance(member.process_instance_id);

  const actorLog = instance?.actor_log ?? [];
  const currentEl = instance?.hitl_tasks?.find((t) => t.status === "open" || t.status === "claimed")?.element_id;
  const failedEl =
    instance?.status === "failed" ? actorLog[actorLog.length - 1]?.element_id ?? null : null;
  const steps = deriveSteps(pack, actorLog, { currentElementId: currentEl, failedElementId: failedEl });
  const markers: BpmnMarker[] = steps.map((s) => ({ elementId: s.element_id, state: s.state }));

  return (
    <div className="mb-3 overflow-hidden rounded-lg border border-border bg-surface">
      <div className="flex flex-wrap items-center gap-3 border-b border-border bg-surface/60 px-4 py-2.5">
        <span className="text-sm font-semibold">
          {member.pack_key} <span className="font-normal text-muted-foreground">@{member.pack_version}</span>
        </span>
        <IdMono value={member.process_instance_id} />
        <MemberStatusChip status={member.status} />
        {member.late && (
          <span className="rounded border border-attention/40 bg-attention-muted px-1.5 py-0.5 text-[10px] font-medium text-attention">
            ⚠ late join
          </span>
        )}
        <span className="flex-1" />
        <Link
          to={`/instances/${member.process_instance_id}`}
          className="inline-flex items-center gap-1 text-xs text-agent hover:underline"
        >
          Open instance <ArrowUpRight className="size-3.5" />
        </Link>
      </div>
      <div className="p-3">
        {bpmn ? (
          <BpmnViewer xml={bpmn} markers={markers} className="h-[300px]" controls />
        ) : (
          <p className="px-2 py-8 text-center text-sm text-muted-foreground">
            Diagram unavailable for {member.pack_key}@{member.pack_version}.
          </p>
        )}
      </div>
    </div>
  );
}
