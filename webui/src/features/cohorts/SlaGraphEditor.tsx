import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import {
  CLOSE_NODE,
  START_NODE,
  type CohortEdge,
  type CohortNode,
  type EdgeSla,
  type EndToEndSla,
  type ExpectationGraph,
  type NodeSla,
} from "@/api/types";

const OWNERS = ["external", "amendia", "shared"] as const;
const CLOCKS = ["wall", "business"] as const;
const MOMENTS = ["arrival", "completion"] as const;
const SPLITS = ["and", "xor"] as const;
const NODE_TYPES = ["expected", "conditional"] as const;

export const EMPTY_GRAPH: ExpectationGraph = { nodes: [], edges: [], end_to_end_sla: null };

/** True when the graph declares nothing — the definition should send `null` (clear) rather than an empty graph. */
export function isEmptyGraph(g: ExpectationGraph | null | undefined): boolean {
  return !g || (g.nodes.length === 0 && g.edges.length === 0 && !g.end_to_end_sla);
}

function slaSummary(sla: EdgeSla | NodeSla | EndToEndSla): string {
  const owner = (sla as EdgeSla).owner ?? "amendia";
  const atRisk = sla.at_risk_seconds ? ` · at-risk ${sla.at_risk_seconds}s` : "";
  return `${owner} · ${sla.deadline_seconds}s${atRisk} · ${sla.clock ?? "wall"}`;
}

// --------------------------------------------------------------------------- #
// Read view — compact tables
// --------------------------------------------------------------------------- #
export function SlaGraphView({ graph }: { graph: ExpectationGraph | null | undefined }) {
  if (isEmptyGraph(graph)) {
    return <p className="py-4 text-center text-sm text-muted-foreground">No SLAs declared — this cohort is a pure observer.</p>;
  }
  const g = graph!;
  return (
    <div className="space-y-4">
      {g.nodes.length > 0 && (
        <div>
          <p className="mb-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">Nodes (segments)</p>
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent"><TableHead>Node</TableHead><TableHead>Type</TableHead><TableHead>Runtime SLA</TableHead></TableRow>
            </TableHeader>
            <TableBody>
              {g.nodes.map((n) => (
                <TableRow key={n.node_id}>
                  <TableCell className="font-mono text-sm">{n.node_id}</TableCell>
                  <TableCell className="text-sm">{n.node_type ?? "expected"}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{n.runtime_sla ? slaSummary(n.runtime_sla) : "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {g.edges.length > 0 && (
        <div>
          <p className="mb-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">Edges (precedence expectations)</p>
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent"><TableHead>From → To</TableHead><TableHead>Split</TableHead><TableHead>SLA</TableHead></TableRow>
            </TableHeader>
            <TableBody>
              {g.edges.map((e, i) => (
                <TableRow key={`${e.from_node}->${e.to_node}-${i}`}>
                  <TableCell className="font-mono text-xs">{e.from_node} → {e.to_node}</TableCell>
                  <TableCell className="text-sm uppercase">{e.split}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {e.sla ? `${e.sla.anchor_moment ?? "completion"}→${e.sla.satisfy_moment ?? "arrival"} · ${slaSummary(e.sla)}` : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      <div className="rounded-md border border-border bg-surface/60 p-3">
        <p className="text-[11px] uppercase tracking-wide text-muted-foreground">End-to-end SLA (open → close)</p>
        <p className="mt-1 text-sm">{g.end_to_end_sla ? slaSummary(g.end_to_end_sla) : <span className="text-muted-foreground">—</span>}</p>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- #
// Edit view — tabular editors
// --------------------------------------------------------------------------- #
const selCls = "h-8 rounded-md border border-input bg-transparent px-2 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function Sel({ value, onChange, options, ariaLabel, className }: {
  value: string; onChange: (v: string) => void; options: readonly string[]; ariaLabel: string; className?: string;
}) {
  return (
    <select aria-label={ariaLabel} value={value} onChange={(e) => onChange(e.target.value)} className={cn(selCls, className)}>
      {options.map((o) => <option key={o} value={o}>{o}</option>)}
    </select>
  );
}

function NumBox({ value, onChange, ariaLabel }: { value: number; onChange: (n: number) => void; ariaLabel: string }) {
  return (
    <Input type="number" min={0} aria-label={ariaLabel} value={value}
           onChange={(e) => onChange(Math.max(0, Number(e.target.value) || 0))}
           className="h-8 w-20 text-xs" />
  );
}

/** Shared SLA field cluster (deadline/at-risk seconds + clock + owner; edges add anchor/satisfy moments). */
function SlaFields<T extends EdgeSla | NodeSla | EndToEndSla>({ sla, onChange, edge }: {
  sla: T; onChange: (s: T) => void; edge?: boolean;
}) {
  const set = (patch: Record<string, unknown>) => onChange({ ...sla, ...patch } as T);
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {edge && (
        <>
          <Sel ariaLabel="anchor moment" options={MOMENTS} value={(sla as EdgeSla).anchor_moment ?? "completion"}
               onChange={(v) => set({ anchor_moment: v })} />
          <span className="text-[10px] text-muted-foreground">→</span>
          <Sel ariaLabel="satisfy moment" options={MOMENTS} value={(sla as EdgeSla).satisfy_moment ?? "arrival"}
               onChange={(v) => set({ satisfy_moment: v })} />
        </>
      )}
      <span className="text-[10px] text-muted-foreground">deadline</span>
      <NumBox ariaLabel="deadline seconds" value={sla.deadline_seconds} onChange={(n) => set({ deadline_seconds: n })} />
      <span className="text-[10px] text-muted-foreground">at-risk</span>
      <NumBox ariaLabel="at-risk seconds" value={sla.at_risk_seconds ?? 0} onChange={(n) => set({ at_risk_seconds: n })} />
      <Sel ariaLabel="clock" options={CLOCKS} value={sla.clock ?? "wall"} onChange={(v) => set({ clock: v })} />
      <Sel ariaLabel="owner" options={OWNERS} value={(sla as EdgeSla).owner ?? "amendia"} onChange={(v) => set({ owner: v })} />
    </div>
  );
}

export function SlaGraphEditor({ graph, memberPackKeys, onChange }: {
  graph: ExpectationGraph; memberPackKeys: string[]; onChange: (g: ExpectationGraph) => void;
}) {
  const nodeIds = graph.nodes.map((n) => n.node_id);
  const fromOptions = [START_NODE, ...nodeIds];
  const toOptions = [...nodeIds, CLOSE_NODE];
  const addableMembers = memberPackKeys.filter((k) => !nodeIds.includes(k));

  const setNodes = (nodes: CohortNode[]) => onChange({ ...graph, nodes });
  const setEdges = (edges: CohortEdge[]) => onChange({ ...graph, edges });

  const patchNode = (i: number, patch: Partial<CohortNode>) =>
    setNodes(graph.nodes.map((n, j) => (j === i ? { ...n, ...patch } : n)));
  const patchEdge = (i: number, patch: Partial<CohortEdge>) =>
    setEdges(graph.edges.map((e, j) => (j === i ? { ...e, ...patch } : e)));

  return (
    <div className="space-y-5">
      {/* Nodes */}
      <div>
        <p className="mb-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">Nodes (segments)</p>
        {graph.nodes.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent"><TableHead>Node</TableHead><TableHead>Type</TableHead><TableHead>Runtime SLA (arrival→completion)</TableHead><TableHead /></TableRow>
            </TableHeader>
            <TableBody>
              {graph.nodes.map((n, i) => (
                <TableRow key={i}>
                  <TableCell className="font-mono text-xs">{n.node_id}</TableCell>
                  <TableCell><Sel ariaLabel={`node ${n.node_id} type`} options={NODE_TYPES} value={n.node_type ?? "expected"} onChange={(v) => patchNode(i, { node_type: v as CohortNode["node_type"] })} /></TableCell>
                  <TableCell>
                    {n.runtime_sla ? (
                      <div className="flex items-center gap-2">
                        <SlaFields sla={n.runtime_sla} onChange={(s) => patchNode(i, { runtime_sla: s })} />
                        <Button size="icon" variant="ghost" aria-label="remove runtime sla" onClick={() => patchNode(i, { runtime_sla: null })}><X /></Button>
                      </div>
                    ) : (
                      <Button size="sm" variant="outline" onClick={() => patchNode(i, { runtime_sla: { deadline_seconds: 3600, at_risk_seconds: 0, clock: "wall", owner: "amendia" } })}><Plus className="size-3.5" /> SLA</Button>
                    )}
                  </TableCell>
                  <TableCell className="text-right"><Button size="icon" variant="ghost" aria-label={`remove node ${n.node_id}`} onClick={() => setNodes(graph.nodes.filter((_, j) => j !== i))}><Trash2 className="size-3.5" /></Button></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        <AddNodeRow addableMembers={addableMembers} existing={nodeIds}
          onAdd={(id) => setNodes([...graph.nodes, { node_id: id, node_type: "expected", runtime_sla: null }])} />
      </div>

      {/* Edges */}
      <div>
        <p className="mb-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">Edges (precedence expectations)</p>
        {graph.edges.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent"><TableHead>From</TableHead><TableHead>To</TableHead><TableHead>Split</TableHead><TableHead>SLA</TableHead><TableHead /></TableRow>
            </TableHeader>
            <TableBody>
              {graph.edges.map((e, i) => (
                <TableRow key={i}>
                  <TableCell><Sel ariaLabel={`edge ${i} from`} options={fromOptions} value={e.from_node} onChange={(v) => patchEdge(i, { from_node: v })} /></TableCell>
                  <TableCell><Sel ariaLabel={`edge ${i} to`} options={toOptions} value={e.to_node} onChange={(v) => patchEdge(i, { to_node: v })} /></TableCell>
                  <TableCell><Sel ariaLabel={`edge ${i} split`} options={SPLITS} value={e.split} onChange={(v) => patchEdge(i, { split: v as CohortEdge["split"] })} /></TableCell>
                  <TableCell>
                    {e.sla ? (
                      <div className="flex items-center gap-2">
                        <SlaFields edge sla={e.sla} onChange={(s) => patchEdge(i, { sla: s })} />
                        <Button size="icon" variant="ghost" aria-label="remove edge sla" onClick={() => patchEdge(i, { sla: null })}><X /></Button>
                      </div>
                    ) : (
                      <Button size="sm" variant="outline" onClick={() => patchEdge(i, { sla: { anchor_moment: "completion", satisfy_moment: "arrival", deadline_seconds: 3600, at_risk_seconds: 0, clock: "wall", owner: "external" } })}><Plus className="size-3.5" /> SLA</Button>
                    )}
                  </TableCell>
                  <TableCell className="text-right"><Button size="icon" variant="ghost" aria-label={`remove edge ${i}`} onClick={() => setEdges(graph.edges.filter((_, j) => j !== i))}><Trash2 className="size-3.5" /></Button></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        <div className="mt-3">
          <Button size="sm" variant="outline" disabled={nodeIds.length === 0}
            onClick={() => setEdges([...graph.edges, { from_node: START_NODE, to_node: nodeIds[0] ?? CLOSE_NODE, split: "and", sla: null }])}>
            <Plus className="size-3.5" /> Add edge
          </Button>
          {nodeIds.length === 0 && <span className="ml-2 text-xs text-muted-foreground">add a node first</span>}
        </div>
      </div>

      {/* End-to-end */}
      <div className="rounded-md border border-border bg-surface/60 p-3">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">End-to-end SLA (open → close)</p>
          {graph.end_to_end_sla ? (
            <Button size="sm" variant="ghost" aria-label="remove end-to-end sla" onClick={() => onChange({ ...graph, end_to_end_sla: null })}><X /> Remove</Button>
          ) : (
            <Button size="sm" variant="outline" onClick={() => onChange({ ...graph, end_to_end_sla: { deadline_seconds: 86400, at_risk_seconds: 0, clock: "wall", owner: "shared" } })}><Plus className="size-3.5" /> Add</Button>
          )}
        </div>
        {graph.end_to_end_sla && <SlaFields sla={graph.end_to_end_sla} onChange={(s) => onChange({ ...graph, end_to_end_sla: s })} />}
      </div>
    </div>
  );
}

function X() {
  return <span className="text-xs" aria-hidden>✕</span>;
}

function AddNodeRow({ addableMembers, existing, onAdd }: {
  addableMembers: string[]; existing: string[]; onAdd: (id: string) => void;
}) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <span className="text-xs font-medium text-muted-foreground">+ Add node:</span>
      {addableMembers.length > 0 && (
        <select aria-label="add member node" defaultValue="" className={selCls}
          onChange={(e) => { if (e.target.value) { onAdd(e.target.value); e.currentTarget.value = ""; } }}>
          <option value="">from member pack…</option>
          {addableMembers.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
      )}
      <FreeNode existing={existing} onAdd={onAdd} />
    </div>
  );
}

function FreeNode({ existing, onAdd }: { existing: string[]; onAdd: (id: string) => void }) {
  return (
    <form className="flex items-center gap-1.5" onSubmit={(e) => {
      e.preventDefault();
      const el = (e.currentTarget.elements.namedItem("node") as HTMLInputElement);
      const v = el.value.trim();
      if (v && v !== START_NODE && v !== CLOSE_NODE && !existing.includes(v)) { onAdd(v); el.value = ""; }
    }}>
      <Input name="node" placeholder="or node_id…" aria-label="new node id" className="h-8 w-40 font-mono text-xs" />
      <Button size="sm" variant="outline" type="submit"><Plus className="size-3.5" /> Add</Button>
    </form>
  );
}
