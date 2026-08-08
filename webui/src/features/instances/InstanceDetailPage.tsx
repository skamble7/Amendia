import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/primitives";
import { ConnectivityState } from "@/components/ConnectivityState";
import { isConnectivityError } from "@/api/client";
import { StepTracker } from "@/components/StepTracker";
import { deriveSteps } from "@/lib/steps";
import { formatDurationShort } from "@/lib/format";
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
import { InstanceHeader } from "./components/InstanceHeader";
import { KpiStrip } from "./components/KpiStrip";
import { ActivityFeed } from "./components/ActivityFeed";
import { ArtifactAccordion } from "./components/ArtifactAccordion";
import { DecisionTrail } from "./components/DecisionTrail";
import { LineageGraph } from "./components/LineageGraph";
import { TraceTree } from "./components/TraceTree";
import { AuditEvents } from "./components/AuditEvents";
import type { Binding } from "@/api/types";

function scrollToSpan(elementId: string) {
  const el = document.getElementById(`trace-el-${elementId}`);
  if (el && typeof el.scrollIntoView === "function") el.scrollIntoView({ behavior: "smooth", block: "center" });
}

export function InstanceDetailPage() {
  const { instanceId } = useParams();
  const [tab, setTab] = useState("overview");
  const { data: instance, isLoading, isFetching, error } = useInstance(instanceId);
  const { data: pack } = usePack(instance?.instance.pack_key, instance?.instance.pack_version);
  const { data: state } = useInstanceState(instanceId);

  // GLEA read-models, keyed by the instance's correlation_id. Each degrades to null (glea unreachable /
  // not deployed) so the page still renders the core agent-runtime view.
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
  // ADR-062: `terminal` still drives the duration display below, but NOT the diagram — `done` is actor_log-only.
  const steps = deriveSteps(pack, instance.actor_log, { currentElementId: currentEl, failedElementId: failedEl });
  const durationText = formatDurationShort(
    instance.instance.created_at,
    terminal ? instance.instance.updated_at : undefined,
  );

  // schema ref per artifact name, from the pack bindings outputs (for schema-tagged rendering)
  const schemaByArtifact = new Map<string, string>();
  for (const b of (pack?.bindings ?? []) as Binding[]) {
    for (const out of b.outputs ?? []) if (out.name && out.schema) schemaByArtifact.set(out.name, out.schema);
  }
  // artifact_key -> name, so a glea decision-trail/lineage ref (art.x) resolves to the runtime artifact.
  const artifactKeyToName = new Map<string, string>();
  for (const [name, schemaRef] of schemaByArtifact) {
    const key = schemaRef.split("@")[0];
    if (key) artifactKeyToName.set(key, name);
  }
  // GLEA-derived enrichment (all empty when glea is absent — pure presentation): the human role per
  // gate, the agent rationale per element, and the producer element per artifact (from lineage).
  const roleByElement = new Map<string, string>();
  for (const g of trail?.gates ?? []) if (g.role) roleByElement.set(g.element_id, g.role);
  const rationaleByElement = new Map<string, string>();
  for (const ev of audit?.events ?? []) {
    const r = ev.kind === "artifact_committed" ? (ev.payload?.rationale as string | undefined) : undefined;
    if (r && ev.element_id) rationaleByElement.set(ev.element_id, r);
  }
  const producerByArtifactName = new Map<string, string>();
  for (const n of lineage?.nodes ?? []) {
    const name = artifactKeyToName.get(n.artifact_key);
    if (name && n.element_id) producerByArtifactName.set(name, n.element_id);
  }

  const viewTrace = trace
    ? (elementId: string) => {
        setTab("observability");
        setTimeout(() => scrollToSpan(elementId), 60);
      }
    : undefined;

  const govCount = trail?.count ?? audit?.count;

  return (
    <>
      <div className="mb-4">
        <Link to="/instances" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" /> Instances
        </Link>
      </div>

      <InstanceHeader
        instance={instance}
        stepCount={steps.length}
        durationText={durationText}
        live={isFetching && !terminal}
      />

      {instance.instance.last_error && (
        <Card className="mb-4 border-danger/40 bg-danger-muted/20">
          <CardContent className="p-4 text-sm text-danger">{instance.instance.last_error}</CardContent>
        </Card>
      )}

      <KpiStrip durationText={durationText} metrics={metrics} />

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="artifacts">Artifacts ({instance.artifact_names.length})</TabsTrigger>
          <TabsTrigger value="governance">Governance{govCount != null ? ` (${govCount})` : ""}</TabsTrigger>
          <TabsTrigger value="observability">Observability</TabsTrigger>
        </TabsList>

        {/* --- Overview: step tracker + activity feed --- */}
        <TabsContent value="overview">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[300px_1fr]">
            <Card>
              <CardHeader><CardTitle>Step tracker</CardTitle></CardHeader>
              <CardContent><StepTracker steps={steps} /></CardContent>
            </Card>
            <div className="space-y-4">
              <Card>
                <CardHeader className="flex-row items-center justify-between">
                  <CardTitle>Activity</CardTitle>
                  <span className="text-xs text-muted-foreground">{instance.actor_log.length} entries · newest first</span>
                </CardHeader>
                <CardContent>
                  <ActivityFeed
                    entries={instance.actor_log}
                    roleByElement={roleByElement}
                    rationaleByElement={rationaleByElement}
                    onViewTrace={viewTrace}
                  />
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Checkpoints</CardTitle></CardHeader>
                <CardContent className="text-sm text-muted-foreground">
                  {/* ADR-058 §5: reference the real append-only audit rows when available. */}
                  {audit
                    ? `Checkpointed at every step boundary. ${audit.count} audit events recorded.`
                    : `Checkpointed at every step boundary. ${instance.actor_log.length} recorded transitions.`}
                </CardContent>
              </Card>
            </div>
          </div>
        </TabsContent>

        {/* --- Artifacts: collapsible accordion --- */}
        <TabsContent value="artifacts">
          <Card>
            <CardHeader><CardTitle>Artifacts</CardTitle></CardHeader>
            <CardContent>
              <ArtifactAccordion
                instance={instance}
                artifacts={state?.artifacts}
                schemaByArtifact={schemaByArtifact}
                producerByArtifactName={producerByArtifactName}
              />
            </CardContent>
          </Card>
        </TabsContent>

        {/* --- Governance: decision trail + audit events --- */}
        <TabsContent value="governance">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <DecisionTrail trail={trail} artifacts={state?.artifacts} artifactKeyToName={artifactKeyToName} packKey={instance.instance.pack_key} packVersion={instance.instance.pack_version} />
            <AuditEvents audit={audit} />
          </div>
        </TabsContent>

        {/* --- Observability: lineage + trace --- */}
        <TabsContent value="observability">
          <div className="space-y-4">
            <LineageGraph lineage={lineage} />
            <TraceTree trace={trace} />
          </div>
        </TabsContent>
      </Tabs>
    </>
  );
}
