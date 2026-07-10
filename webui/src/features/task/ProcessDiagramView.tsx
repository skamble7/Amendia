import { ArrowLeft } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { IdMono } from "@/components/primitives";
import { cn } from "@/lib/utils";
import { usePackBpmn } from "@/features/registry/queries";
import { BpmnViewer, type BpmnMarker } from "@/features/registry/BpmnViewer";
import { useProcessProgress } from "./useProcessProgress";
import type { HitlTask } from "@/api/types";

/**
 * In-place, full-width view of the pack's ACTUAL BPMN diagram with the live process
 * state painted on top (done / current / failed). Opened from the task detail's
 * "Process progress" card and dismissed via "Back to task" — it replaces the task
 * layout rather than overlaying a modal, mirroring the design.
 */
export function ProcessDiagramView({ task, onBack }: { task: HitlTask; onBack: () => void }) {
  const { steps } = useProcessProgress(task);
  const { data: bpmn } = usePackBpmn(task.pack_key, task.pack_version);
  const markers: BpmnMarker[] = steps.map((s) => ({ elementId: s.element_id, state: s.state }));
  const current = steps.find((s) => s.state === "current");

  return (
    <>
      <div className="mb-4">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" /> Back to task
        </button>
      </div>

      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-0.5">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Process diagram · BPMN
          </p>
          <h1 className="text-xl font-semibold tracking-tight">{task.title}</h1>
        </div>
        <div className="space-y-0.5 text-right text-xs text-muted-foreground">
          <p className="font-mono">
            {task.pack_key}@{task.pack_version}
          </p>
          <IdMono value={task.process_instance_id} />
        </div>
      </div>

      {current && (
        <Card className="mb-4 border-attention/40 bg-attention-muted/20">
          <CardContent className="flex items-center gap-2 p-3 text-sm">
            <span className="size-2 shrink-0 rounded-full bg-attention" />
            Execution is paused, waiting on you at <span className="font-medium">{current.label}</span>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="space-y-3 p-4">
          <BpmnViewer xml={bpmn} markers={markers} className="h-[min(70vh,640px)]" />
          <Legend />
        </CardContent>
      </Card>
    </>
  );
}

function Legend() {
  const items: { label: string; cls: string }[] = [
    { label: "Done", cls: "bg-success/20 border-success/50" },
    { label: "Current", cls: "bg-agent/20 border-agent/60" },
    { label: "Pending", cls: "bg-muted border-border" },
    { label: "Failed", cls: "bg-danger/20 border-danger/50" },
  ];
  return (
    <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5">
          <span className={cn("size-3 rounded-[3px] border", i.cls)} />
          {i.label}
        </span>
      ))}
    </div>
  );
}
