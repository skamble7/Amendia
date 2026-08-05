import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Info, Boxes } from "lucide-react";
import { PageHeader } from "@/app/AppShell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusChip, ActorAvatar, EmptyState, LiveDot } from "@/components/primitives";
import { ConnectivityState } from "@/components/ConnectivityState";
import { isConnectivityError } from "@/api/client";
import { StepTracker } from "@/components/StepTracker";
import { ArtifactView } from "@/components/artifact/ArtifactView";
import { deriveSteps } from "@/lib/steps";
import { formatDateTime } from "@/lib/format";
import {
  useInstance,
  useInstanceAudit,
  useInstanceMetrics,
  useInstanceState,
  useDecisionTrail,
  useLineage,
  usePack,
  useTraceTree,
} from "./queries";
import { DecisionTrail } from "./components/DecisionTrail";
import { LineageGraph } from "./components/LineageGraph";
import { TraceTree } from "./components/TraceTree";
import { AuditEvents } from "./components/AuditEvents";
import { MetricsTiles } from "./components/MetricsTiles";
import type { Binding } from "@/api/types";

function scrollToSpan(elementId: string) {
  const el = document.getElementById(`trace-el-${elementId}`);
  if (el && typeof el.scrollIntoView === "function") el.scrollIntoView({ behavior: "smooth", block: "center" });
}

export function InstanceDetailPage() {
  const { instanceId } = useParams();
  const { data: instance, isLoading, isFetching, error } = useInstance(instanceId);
  const { data: pack } = usePack(instance?.instance.pack_key, instance?.instance.pack_version);
  const { data: state } = useInstanceState(instanceId);

  // GLEA read-models, keyed by the instance's correlation_id. Each degrades to null (glea unreachable /
  // not deployed) so the page still renders the core agent-runtime view below.
  const cid = instance?.instance.correlation_id;
  const { data: trail } = useDecisionTrail(cid);
  const { data: lineage } = useLineage(cid);
  const { data: metrics } = useInstanceMetrics(cid);
  const { data: trace } = useTraceTree(cid);
  const { data: audit } = useInstanceAudit(cid);

  if (isLoading) {
    return <div className="space-y-4"><Skeleton className="h-8 w-64" /><Skeleton className="h-64 w-full" /></div>;
  }
  if (isConnectivityError(error)) return <ConnectivityState error={error} />;
  if (!instance) {
    return <EmptyState title="Instance not found" description="The id may be invalid." />;
  }

  const terminal = ["completed", "failed", "cancelled"].includes(instance.status);
  const currentEl = instance.hitl_tasks.find((t) => t.status === "open" || t.status === "claimed")?.element_id;
  const failedEl = instance.status === "failed" ? instance.actor_log[instance.actor_log.length - 1]?.element_id : null;
  const steps = deriveSteps(pack, instance.actor_log, { currentElementId: currentEl, failedElementId: failedEl, terminal });

  // schema ref per artifact name, from the pack bindings outputs (for schema-tagged rendering)
  const schemaByArtifact = new Map<string, string>();
  for (const b of (pack?.bindings ?? []) as Binding[]) {
    for (const out of b.outputs ?? []) if (out.name && out.schema) schemaByArtifact.set(out.name, out.schema);
  }
  // artifact_key -> name, so a glea decision-trail ref (art.x) resolves to the runtime artifact value.
  const artifactKeyToName = new Map<string, string>();
  for (const [name, schemaRef] of schemaByArtifact) {
    const key = schemaRef.split("@")[0];
    if (key) artifactKeyToName.set(key, name);
  }
  // GLEA-derived actor-log enrichment: role (from the decision trail) + rationale (from the
  // artifact_committed audit rows, Phase C). Both keyed by element_id; empty when glea is absent.
  const roleByElement = new Map<string, string>();
  for (const g of trail?.gates ?? []) if (g.role) roleByElement.set(g.element_id, g.role);
  const rationaleByElement = new Map<string, string>();
  for (const ev of audit?.events ?? []) {
    const r = ev.kind === "artifact_committed" ? (ev.payload?.rationale as string | undefined) : undefined;
    if (r && ev.element_id) rationaleByElement.set(ev.element_id, r);
  }

  return (
    <>
      <div className="mb-4">
        <Link to="/instances" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" /> Instances
        </Link>
      </div>
      <PageHeader
        title={instance.instance.process_instance_id}
        description={`${instance.instance.pack_key}@${instance.instance.pack_version}`}
        badge={isFetching && !terminal ? <LiveDot /> : undefined}
        actions={
          <div className="flex items-center gap-2">
            {instance.outcome && <Badge variant={instance.outcome === "End_Returned" ? "attention" : "success"}>{instance.outcome}</Badge>}
            <StatusChip kind="instance" value={instance.status} />
          </div>
        }
      />

      {instance.instance.last_error && (
        <Card className="mb-4 border-danger/40 bg-danger-muted/20">
          <CardContent className="p-4 text-sm text-danger">{instance.instance.last_error}</CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_1fr]">
        {/* Left: step tracker + actor log */}
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>Step tracker</CardTitle></CardHeader>
            <CardContent><StepTracker steps={steps} /></CardContent>
          </Card>

          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle>Actor log</CardTitle>
              <span className="text-xs text-muted-foreground">{instance.actor_log.length} entries</span>
            </CardHeader>
            <CardContent>
              <ol className="space-y-3">
                {instance.actor_log.map((e, i) => {
                  const role = e.kind === "human" ? roleByElement.get(e.element_id) : undefined;
                  const rationale = rationaleByElement.get(e.element_id);
                  return (
                    <li key={i} className="flex items-start gap-3">
                      <ActorAvatar actor={e.actor} kind={e.kind} />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-sm font-medium">{e.element_id}</p>
                          {role ? <Badge variant="outline">{role}</Badge> : null}
                        </div>
                        <p className="text-xs text-muted-foreground">
                          {e.kind === "capability" ? "Agent" : "Human"} · {e.actor} · {formatDateTime(e.at)}
                        </p>
                        {rationale ? (
                          <p className="mt-1 text-xs italic text-muted-foreground">
                            {rationale.length > 180 ? `${rationale.slice(0, 179)}…` : rationale}
                          </p>
                        ) : null}
                      </div>
                      {trace ? (
                        <button
                          type="button"
                          onClick={() => scrollToSpan(e.element_id)}
                          className="shrink-0 text-xs text-muted-foreground hover:text-foreground"
                        >
                          View trace
                        </button>
                      ) : null}
                    </li>
                  );
                })}
              </ol>
            </CardContent>
          </Card>
        </div>

        {/* Right: artifacts + checkpoints */}
        <div className="space-y-4">
          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle className="flex items-center gap-2"><Boxes className="size-4" /> Artifacts</CardTitle>
              <span className="text-xs text-muted-foreground">{instance.artifact_names.length}</span>
            </CardHeader>
            <CardContent className="space-y-4">
              {state ? (
                Object.entries(state.artifacts).map(([name, data]) => (
                  <div key={name} className="rounded-md border border-border p-3">
                    <ArtifactView name={name} data={data as Record<string, unknown>} schemaRef={schemaByArtifact.get(name)} />
                  </div>
                ))
              ) : instance.artifact_names.length > 0 ? (
                <div className="space-y-2">
                  <div className="flex items-start gap-2 rounded-md border border-border bg-surface/60 p-3 text-xs text-muted-foreground">
                    <Info className="mt-0.5 size-3.5 shrink-0" />
                    Artifact data requires the runtime debug API (<code className="font-mono">AGENTRT_ENABLE_DEBUG_API</code>). Names are shown below.
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {instance.artifact_names.map((n) => (
                      <Badge key={n} variant="artifact">{n}</Badge>
                    ))}
                  </div>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">No artifacts yet.</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Checkpoints</CardTitle></CardHeader>
            <CardContent className="text-sm text-muted-foreground">
              {/* ADR-058 §5: reference the real append-only audit rows (glea) when available, falling
                  back to the actor-log transition count when glea is absent. */}
              {audit
                ? `Checkpointed at every step boundary. ${audit.count} audit events recorded.`
                : `Checkpointed at every step boundary. ${instance.actor_log.length} recorded transitions.`}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* ADR-058 Phase E — the GLEA read-model sections (glea-service). Each degrades to a graceful
          "unavailable / no data" state; the core view above always renders. */}
      <div className="mt-6">
        <MetricsTiles metrics={metrics} />
      </div>
      <div className="mt-4">
        <DecisionTrail trail={trail} artifacts={state?.artifacts} artifactKeyToName={artifactKeyToName} />
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <LineageGraph lineage={lineage} />
        <TraceTree trace={trace} />
      </div>
      <div className="mt-4">
        <AuditEvents audit={audit} />
      </div>
    </>
  );
}
