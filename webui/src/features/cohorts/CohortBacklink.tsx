import { Link } from "react-router-dom";
import { Boxes, ArrowRight } from "lucide-react";
import { useCohort } from "./queries";
import type { InstanceDetail } from "@/api/types";

/**
 * ADR-063 Phase 3B: the cohort backlink banner on the instance view. Renders only when the instance joined a
 * cohort (non-null cohort_instance_id); a standalone instance shows nothing. The sibling count is enriched from
 * the cohort read-model when available and omitted if GLEA is unreachable (never blocks the banner).
 */
export function CohortBacklink({ instance }: { instance: InstanceDetail }) {
  const cohortId = instance.cohort_instance_id;
  const { data: cohort } = useCohort(cohortId ?? undefined);
  if (!cohortId) return null;

  const siblings = cohort ? Math.max(0, cohort.member_count - 1) : null;

  return (
    <Link
      to={`/cohorts/${cohortId}`}
      className="mb-5 flex items-center gap-3 rounded-lg border border-border bg-gradient-to-r from-artifact-muted/40 to-agent-muted/20 px-4 py-3 transition-colors hover:border-agent/40"
    >
      <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-surface text-artifact">
        <Boxes className="size-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm">
          Part of cohort <span className="font-medium text-foreground">{instance.cohort_def_id}</span> ·{" "}
          <span className="font-mono text-agent">{cohortId}</span>
        </span>
        <span className="block text-xs text-muted-foreground">
          correlation <span className="font-mono">{instance.cohort_correlation_value}</span>
          {siblings != null && <> · {siblings} sibling {siblings === 1 ? "segment" : "segments"}</>}
        </span>
      </span>
      <span className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-md border border-agent/40 px-3 py-1.5 text-xs text-agent">
        View cohort <ArrowRight className="size-3.5" />
      </span>
    </Link>
  );
}
