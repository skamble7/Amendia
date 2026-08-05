import { Workflow } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { LineageOut } from "@/api/types";

const NODE_W = 156;
const NODE_H = 46;
const GAP_X = 56;
const GAP_Y = 14;
const PAD = 12;

/** Longest-path layering (Kahn): each node's column = the longest producer chain reaching it. Cycle-safe
 * (a node never visited keeps column 0). This turns the producer→consumer edge set into left-to-right
 * columns so the MI fan-in (N iteration nodes in one column → the join in the next) reads naturally. */
function layout(lineage: LineageOut) {
  const nodes = lineage.nodes;
  const ids = new Set(nodes.map((n) => n.span_id));
  const out = new Map<string, string[]>();
  const indeg = new Map<string, number>();
  nodes.forEach((n) => indeg.set(n.span_id, 0));
  for (const e of lineage.edges) {
    if (!ids.has(e.from_span) || !ids.has(e.to_span) || e.from_span === e.to_span) continue;
    if (!out.has(e.from_span)) out.set(e.from_span, []);
    out.get(e.from_span)!.push(e.to_span);
    indeg.set(e.to_span, (indeg.get(e.to_span) ?? 0) + 1);
  }
  const col = new Map<string, number>();
  const work = new Map(indeg);
  const queue = nodes.filter((n) => (indeg.get(n.span_id) ?? 0) === 0).map((n) => n.span_id);
  queue.forEach((id) => col.set(id, 0));
  while (queue.length) {
    const u = queue.shift()!;
    for (const v of out.get(u) ?? []) {
      col.set(v, Math.max(col.get(v) ?? 0, (col.get(u) ?? 0) + 1));
      work.set(v, (work.get(v) ?? 0) - 1);
      if ((work.get(v) ?? 0) === 0) queue.push(v);
    }
  }
  const columns: string[][] = [];
  for (const n of nodes) {
    const c = col.get(n.span_id) ?? 0;
    (columns[c] ??= []).push(n.span_id);
  }
  const pos = new Map<string, { x: number; y: number }>();
  columns.forEach((rows, c) =>
    rows.forEach((id, r) =>
      pos.set(id, { x: PAD + c * (NODE_W + GAP_X), y: PAD + r * (NODE_H + GAP_Y) }),
    ),
  );
  const width = PAD * 2 + Math.max(1, columns.length) * NODE_W + Math.max(0, columns.length - 1) * GAP_X;
  const rowsMax = Math.max(1, ...columns.map((c) => c.length));
  const height = PAD * 2 + rowsMax * NODE_H + (rowsMax - 1) * GAP_Y;
  return { pos, width, height };
}

/** The artifact dataflow DAG (ADR-058 §4) — a lightweight custom SVG (no graph library). Null → note. */
export function LineageGraph({ lineage }: { lineage: LineageOut | null | undefined }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Workflow className="size-4" /> Lineage
        </CardTitle>
      </CardHeader>
      <CardContent>
        {!lineage ? (
          <p className="text-sm text-muted-foreground">Lineage unavailable (glea-service not reachable).</p>
        ) : lineage.nodes.length === 0 ? (
          <p className="text-sm text-muted-foreground">No lineage recorded for this instance.</p>
        ) : (
          (() => {
            const { pos, width, height } = layout(lineage);
            const edges = lineage.edges.filter((e) => pos.has(e.from_span) && pos.has(e.to_span));
            return (
              <div className="overflow-x-auto">
                <svg width={width} height={height} role="img" aria-label="artifact lineage graph">
                  {edges.map((e, i) => {
                    const a = pos.get(e.from_span)!;
                    const b = pos.get(e.to_span)!;
                    const x1 = a.x + NODE_W;
                    const y1 = a.y + NODE_H / 2;
                    const x2 = b.x;
                    const y2 = b.y + NODE_H / 2;
                    const mx = (x1 + x2) / 2;
                    return (
                      <path
                        key={i}
                        d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`}
                        className="fill-none stroke-border"
                        strokeWidth={1.5}
                      />
                    );
                  })}
                  {lineage.nodes.map((n) => {
                    const p = pos.get(n.span_id)!;
                    const label = n.artifact_key.replace(/^art\./, "");
                    const human = n.authored_by_human === true;
                    return (
                      <g key={n.span_id} transform={`translate(${p.x},${p.y})`}>
                        <rect
                          width={NODE_W}
                          height={NODE_H}
                          rx={6}
                          className={human ? "fill-agent-muted stroke-agent/40" : "fill-surface stroke-border"}
                        />
                        <text x={8} y={18} className="fill-foreground text-[11px] font-medium">
                          {label.length > 22 ? `${label.slice(0, 21)}…` : label}
                        </text>
                        <text x={8} y={34} className="fill-muted-foreground text-[10px]">
                          {n.element_id.length > 24 ? `${n.element_id.slice(0, 23)}…` : n.element_id}
                        </text>
                      </g>
                    );
                  })}
                </svg>
                <p className="mt-2 text-xs text-muted-foreground">
                  {lineage.nodes.length} artifacts · {edges.length} flows
                </p>
              </div>
            );
          })()
        )}
      </CardContent>
    </Card>
  );
}
