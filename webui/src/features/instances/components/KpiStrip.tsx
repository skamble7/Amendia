import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { MetricsBundle } from "@/api/types";

function fmtMs(v: number): string {
  if (!v) return "0ms";
  return v >= 1000 ? `${(v / 1000).toFixed(0)}s` : `${Math.round(v)}ms`;
}

function Kpi({ label, value, sub, tone }: {
  label: string;
  value: ReactNode;
  sub?: string;
  tone?: "good" | "zero";
}) {
  return (
    <div className="rounded-lg border border-border bg-surface p-3">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-1.5 text-xl font-semibold tabular-nums tracking-tight",
          tone === "good" && "text-success",
          tone === "zero" && "text-muted-foreground",
        )}
      >
        {value}
      </p>
      {sub ? <p className="mt-0.5 text-[11px] text-muted-foreground">{sub}</p> : null}
    </div>
  );
}

const NA = <span className="text-muted-foreground">—</span>;

/**
 * The always-visible KPI strip (ADR-058 Phase E). Duration comes from the instance state and ALWAYS
 * renders; the other five come from the glea metrics bundle and degrade to "—" when glea is
 * unavailable. Status colors are reserved (success for good/four-eyes, muted for zeros) — from the
 * existing token palette, no per-metric rainbow.
 */
export function KpiStrip({ durationText, metrics }: {
  durationText: string;
  metrics: MetricsBundle | null | undefined;
}) {
  const m = metrics ?? null;
  const decisions = m ? m.hitl_decisions.reduce((a, d) => a + d.count, 0) : 0;
  return (
    <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <Kpi label="Duration" value={durationText} sub="start → end" />

      <Kpi
        label="Approval latency"
        value={m ? <>{fmtMs(m.approval_latency_ms.p50)} <span className="text-sm text-muted-foreground">p50</span></> : NA}
        sub={m ? `${fmtMs(m.approval_latency_ms.p95)} p95 · ${m.approval_latency_ms.count} gates` : "unavailable"}
      />

      <Kpi
        label="Capability p95"
        value={m ? fmtMs(m.capability_duration_ms.p95) : NA}
        sub={m ? `${m.capability_duration_ms.count} spans` : "unavailable"}
      />

      <Kpi
        label="Four-eyes"
        value={m ? <>{m.four_eyes_enforced} <span className="text-sm">✓</span></> : NA}
        sub={m ? "SoD enforced" : "unavailable"}
        tone={m ? (m.four_eyes_enforced > 0 ? "good" : "zero") : undefined}
      />

      <Kpi
        label="Egress denied"
        value={m ? m.egress_denied : NA}
        sub={m ? `${decisions} decisions` : "unavailable"}
        tone={m ? (m.egress_denied > 0 ? undefined : "zero") : undefined}
      />

      <Kpi
        label="SLA breaches"
        value={m ? m.sla_breaches : NA}
        sub={m ? "timers" : "unavailable"}
        tone={m ? (m.sla_breaches > 0 ? undefined : "zero") : undefined}
      />
    </div>
  );
}
