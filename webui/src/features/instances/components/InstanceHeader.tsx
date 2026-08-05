import { Badge } from "@/components/ui/badge";
import { StatusChip, LiveDot } from "@/components/primitives";
import type { InstanceDetail } from "@/api/types";

interface Props {
  instance: InstanceDetail;
  stepCount: number;
  durationText: string;
  live: boolean;
}

/** Summary header (ADR-058 Phase E redesign): mono instance id + a subtitle line, with the outcome +
 * status pills on the right. All from the agent-runtime instance state (always renders). */
export function InstanceHeader({ instance, stepCount, durationText, live }: Props) {
  const cid = instance.instance.correlation_id;
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <h1 className="truncate font-mono text-2xl font-semibold tracking-tight">
            {instance.instance.process_instance_id}
          </h1>
          {live ? <LiveDot /> : null}
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          <span className="text-foreground/80">
            {instance.instance.pack_key}@{instance.instance.pack_version}
          </span>
          {" · "}correlation <span className="font-mono">{cid}</span>
          {" · "}
          {stepCount} steps
          {" · "}
          {durationText}
        </p>
      </div>
      <div className="flex flex-wrap items-center justify-end gap-2">
        {instance.outcome ? (
          <Badge variant={instance.outcome === "End_Returned" ? "attention" : "success"}>
            {instance.outcome}
          </Badge>
        ) : null}
        <StatusChip kind="instance" value={instance.status} />
      </div>
    </div>
  );
}
