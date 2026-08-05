import type { ReactNode } from "react";
import { BarChart3 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { MetricsBundle } from "@/api/types";

function fmtMs(v: number): string {
  if (!v) return "0ms";
  return v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${Math.round(v)}ms`;
}

function Tile({ label, value, sub }: { label: string; value: ReactNode; sub?: string }) {
  return (
    <div className="rounded-md border border-border bg-surface/60 p-3">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-semibold tabular-nums">{value}</p>
      {sub ? <p className="text-xs text-muted-foreground">{sub}</p> : null}
    </div>
  );
}

/** Phase D metrics bundle rendered as tiles. Null (glea unreachable) → a graceful note. */
export function MetricsTiles({ metrics }: { metrics: MetricsBundle | null | undefined }) {
  const decisionsTotal = metrics ? metrics.hitl_decisions.reduce((a, d) => a + d.count, 0) : 0;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BarChart3 className="size-4" /> Metrics
        </CardTitle>
      </CardHeader>
      <CardContent>
        {!metrics ? (
          <p className="text-sm text-muted-foreground">Metrics unavailable (glea-service not reachable).</p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              <Tile
                label="Approval latency p50"
                value={fmtMs(metrics.approval_latency_ms.p50)}
                sub={`p95 ${fmtMs(metrics.approval_latency_ms.p95)}`}
              />
              <Tile
                label="Capability exec p50"
                value={fmtMs(metrics.capability_duration_ms.p50)}
                sub={`p95 ${fmtMs(metrics.capability_duration_ms.p95)}`}
              />
              <Tile label="Four-eyes enforced" value={metrics.four_eyes_enforced} />
              <Tile label="Egress denied" value={metrics.egress_denied} />
              <Tile label="SLA breaches" value={metrics.sla_breaches} />
              <Tile label="HITL decisions" value={decisionsTotal} />
            </div>
            {metrics.hitl_decisions.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {metrics.hitl_decisions.map((d, i) => (
                  <Badge key={i} variant="outline">
                    {d.decision} · {d.role || "—"} · {d.count}
                  </Badge>
                ))}
              </div>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}
