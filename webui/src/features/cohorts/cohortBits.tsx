import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { CohortRollup, CohortState, MemberStatus, SlaState } from "@/api/types";

const STATE_META: Record<CohortState, { label: string; variant: "agent" | "attention" | "success"; pulse: boolean }> = {
  open: { label: "Open", variant: "agent", pulse: false },
  closing: { label: "Closing", variant: "attention", pulse: true },
  closed: { label: "Closed", variant: "success", pulse: false },
};

const STATE_DOT: Record<CohortState, string> = {
  open: "bg-agent",
  closing: "bg-attention",
  closed: "bg-success",
};

/** Cohort lifecycle chip: open / closing (pulsing amber) / closed. */
export function CohortStateChip({ state, className }: { state: CohortState; className?: string }) {
  const meta = STATE_META[state] ?? STATE_META.open;
  return (
    <Badge variant={meta.variant} className={cn("gap-1.5", className)} aria-label={`cohort state: ${meta.label}`}>
      <span className={cn("size-1.5 rounded-full", STATE_DOT[state], meta.pulse && "animate-pulse")} />
      {meta.label}
    </Badge>
  );
}

const MEMBER_DOT: Record<MemberStatus, string> = {
  done: "bg-success",
  running: "bg-agent",
  failed: "bg-danger",
};
const MEMBER_LABEL: Record<MemberStatus, string> = { done: "Completed", running: "Running", failed: "Failed" };

export function MemberStatusChip({ status, className }: { status: MemberStatus; className?: string }) {
  const variant = status === "done" ? "success" : status === "failed" ? "danger" : "agent";
  return (
    <Badge variant={variant} className={cn("gap-1.5", className)}>
      <span className={cn("size-1.5 rounded-full", MEMBER_DOT[status], status === "running" && "animate-pulse")} />
      {MEMBER_LABEL[status]}
    </Badge>
  );
}

// --------------------------------------------------------------------------- #
// ADR-064 P4 — cohort SLA bits (observability-grade, problem-focused).
// --------------------------------------------------------------------------- #
const SLA_META: Record<SlaState, { label: string; variant: "danger" | "attention" | "success" | "outline"; dot: string }> = {
  breached: { label: "Breached", variant: "danger", dot: "bg-danger" },
  at_risk: { label: "At risk", variant: "attention", dot: "bg-attention" },
  satisfied: { label: "Satisfied", variant: "success", dot: "bg-success" },
  voided: { label: "Voided", variant: "outline", dot: "bg-muted-foreground" },
};

/** SLA state chip: breached (red) / at-risk (amber) / satisfied (green) / voided (muted). */
export function SlaStateChip({ state, className }: { state: SlaState | string; className?: string }) {
  const meta = SLA_META[state as SlaState] ?? SLA_META.voided;
  return (
    <Badge variant={meta.variant} className={cn("gap-1.5", className)} aria-label={`sla state: ${meta.label}`}>
      <span className={cn("size-1.5 rounded-full", meta.dot, state === "at_risk" && "animate-pulse")} />
      {meta.label}
    </Badge>
  );
}

/** Compact list badges: a red breach count + an amber at-risk count. Zero → nothing (degrading). */
export function SlaBadges({ breaches, atRisk, className }: { breaches?: number; atRisk?: number; className?: string }) {
  const b = breaches ?? 0;
  const a = atRisk ?? 0;
  if (b === 0 && a === 0) return null;
  return (
    <span className={cn("inline-flex items-center gap-1", className)}>
      {b > 0 && (
        <span className="rounded border border-danger/40 bg-danger-muted px-1.5 py-0.5 text-[10px] font-medium text-danger"
              title={`${b} SLA breach${b === 1 ? "" : "es"}`}>
          ⚠ {b}
        </span>
      )}
      {a > 0 && (
        <span className="rounded border border-attention/40 bg-attention-muted px-1.5 py-0.5 text-[10px] font-medium text-attention"
              title={`${a} SLA at risk`}>
          {a} at-risk
        </span>
      )}
    </span>
  );
}

/** A compact done/running/failed rollup bar + counts (late-joins excluded upstream by the read-model). */
export function RollupBar({ rollup, anomalies }: { rollup: CohortRollup; anomalies?: number }) {
  const total = rollup.done + rollup.running + rollup.failed || 1;
  const pct = (n: number) => `${(n / total) * 100}%`;
  const counts = [
    rollup.done ? `${rollup.done} done` : null,
    rollup.running ? `${rollup.running} run` : null,
    rollup.failed ? `${rollup.failed} fail` : null,
  ]
    .filter(Boolean)
    .join(" · ") || "—";
  return (
    <div className="flex items-center gap-2">
      <span className="flex h-1.5 w-20 overflow-hidden rounded-full bg-muted" aria-hidden>
        {rollup.done > 0 && <i className="h-full bg-success" style={{ width: pct(rollup.done) }} />}
        {rollup.running > 0 && <i className="h-full bg-agent" style={{ width: pct(rollup.running) }} />}
        {rollup.failed > 0 && <i className="h-full bg-danger" style={{ width: pct(rollup.failed) }} />}
      </span>
      <span className="text-xs text-muted-foreground">{counts}</span>
      {anomalies ? (
        <span className="rounded border border-attention/40 bg-attention-muted px-1.5 py-0.5 text-[10px] font-medium text-attention">
          ⚠ {anomalies} late-join
        </span>
      ) : null}
    </div>
  );
}
