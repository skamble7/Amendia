import type { ComponentType } from "react";
import { Badge } from "@/components/ui/badge";
import { DiffRow, DiffList } from "./CorrectionDiff";
import { FieldGroup } from "./ArtifactView";
import { humanizeKey, type JsonSchema } from "./schema";

export interface CustomRendererProps {
  data: Record<string, unknown>;
  schema?: JsonSchema;
}

/**
 * Custom artifact renderers keyed by artifact_key. Anything not registered here
 * falls through to the generic schema walker in ArtifactView. This is the
 * extension seam the design calls for (e.g. a bespoke repair diff).
 */

/** art.payment.repair_instruction — corrections[].{field, before, after} + justification. */
function RepairInstruction({ data }: CustomRendererProps) {
  const corrections = (data.corrections as Array<Record<string, unknown>>) ?? [];
  return (
    <div className="space-y-3">
      <DiffList>
        {corrections.map((c, i) => (
          <DiffRow key={i} field={String(c.field)} before={c.before} after={c.after} />
        ))}
      </DiffList>
      {typeof data.justification === "string" && (
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Justification</p>
          <p className="text-sm">{data.justification}</p>
        </div>
      )}
      <div className="flex items-center gap-2 text-sm">
        <span className="text-muted-foreground">Requires re-screen</span>
        <Badge variant={data.requires_rescreen ? "attention" : "default"}>{data.requires_rescreen ? "Yes" : "No"}</Badge>
      </div>
    </div>
  );
}

/** art.payment.repair_verdict — proposed_correction {field, current_value, proposed_value}. */
function RepairVerdict({ data, schema }: CustomRendererProps) {
  const pc = data.proposed_correction as Record<string, unknown> | undefined;
  const { proposed_correction: _pc, ...rest } = data;
  return (
    <div className="space-y-3">
      <FieldGroup data={rest} schema={schema} />
      {pc && (
        <div className="space-y-1.5">
          <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {humanizeKey("proposed_correction")}
          </p>
          <DiffRow field={String(pc.field)} before={pc.current_value} after={pc.proposed_value} />
        </div>
      )}
    </div>
  );
}

export const CUSTOM_RENDERERS: Record<string, ComponentType<CustomRendererProps>> = {
  "art.payment.repair_instruction": RepairInstruction,
  "art.payment.repair_verdict": RepairVerdict,
};
