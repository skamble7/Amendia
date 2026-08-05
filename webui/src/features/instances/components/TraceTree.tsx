import { Activity } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { TraceTreeOut } from "@/api/types";

function fmtDur(ns: number): string {
  const ms = ns / 1_000_000;
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`;
  if (ms >= 1) return `${ms.toFixed(1)}ms`;
  return `${Math.round(ns / 1000)}µs`;
}

/** In-view execution waterfall (ADR-058 §6) — an indented tree with relative duration bars, from the
 * glea trace read-model (no external trace UI, no graph lib). Each row anchors by element_id so the
 * actor log's "View trace" can focus it. Null → a graceful note. */
export function TraceTree({ trace }: { trace: TraceTreeOut | null | undefined }) {
  const spans = trace?.spans ?? [];
  const minStart = spans.length ? Math.min(...spans.map((s) => s.start_ns)) : 0;
  const maxEnd = spans.length ? Math.max(...spans.map((s) => s.start_ns + s.duration_ns)) : 1;
  const total = Math.max(1, maxEnd - minStart);
  const seenEl = new Set<string>();

  return (
    <Card id="trace-view">
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2">
          <Activity className="size-4" /> Trace
        </CardTitle>
        {trace ? <span className="text-xs text-muted-foreground">{spans.length} spans</span> : null}
      </CardHeader>
      <CardContent>
        {!trace ? (
          <p className="text-sm text-muted-foreground">Trace unavailable (glea-service not reachable).</p>
        ) : spans.length === 0 ? (
          <p className="text-sm text-muted-foreground">No spans recorded for this instance.</p>
        ) : (
          <ol className="space-y-1">
            {spans.map((s) => {
              const left = ((s.start_ns - minStart) / total) * 100;
              const width = Math.max(1, (s.duration_ns / total) * 100);
              const anchor = s.element_id && !seenEl.has(s.element_id);
              if (s.element_id) seenEl.add(s.element_id);
              return (
                <li
                  key={s.span_id}
                  id={anchor ? `trace-el-${s.element_id}` : undefined}
                  className="grid grid-cols-[minmax(120px,1fr)_2fr_auto] items-center gap-2 text-xs"
                >
                  <span
                    className="truncate font-mono"
                    style={{ paddingLeft: `${Math.min(s.depth, 8) * 10}px` }}
                    title={s.name}
                  >
                    {s.name || s.span_id.slice(0, 8)}
                  </span>
                  <span className="relative h-3 rounded bg-surface">
                    <span
                      className={`absolute top-0 h-3 rounded ${
                        s.actor_kind === "capability" ? "bg-agent/60" : "bg-process/50"
                      }`}
                      style={{ left: `${left}%`, width: `${width}%` }}
                    />
                  </span>
                  <span className="tabular-nums text-muted-foreground">{fmtDur(s.duration_ns)}</span>
                </li>
              );
            })}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}
