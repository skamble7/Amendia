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
import { useInstance, useInstanceState, usePack } from "./queries";
import type { Binding } from "@/api/types";

export function InstanceDetailPage() {
  const { instanceId } = useParams();
  const { data: instance, isLoading, isFetching, error } = useInstance(instanceId);
  const { data: pack } = usePack(instance?.instance.pack_key, instance?.instance.pack_version);
  const { data: state } = useInstanceState(instanceId);

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
                {instance.actor_log.map((e, i) => (
                  <li key={i} className="flex items-start gap-3">
                    <ActorAvatar actor={e.actor} kind={e.kind} />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium">{e.element_id}</p>
                      <p className="text-xs text-muted-foreground">
                        {e.kind === "capability" ? "Agent" : "Human"} · {e.actor} · {formatDateTime(e.at)}
                      </p>
                    </div>
                  </li>
                ))}
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
              {/* backend-aggregation: no public checkpoint count; the runtime checkpoints at every
                  node boundary (langgraph-checkpoint-mongodb). Surfaced indirectly via the actor log. */}
              Checkpointed at every step boundary. {instance.actor_log.length} recorded transitions.
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}
