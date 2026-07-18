import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { PageHeader } from "@/app/AppShell";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { ModeBadge } from "@/components/primitives";
import { EmptyState } from "@/components/primitives";
import { ConnectivityState } from "@/components/ConnectivityState";
import { isConnectivityError } from "@/api/client";
import { StatusBadge } from "./RegistryPage";
import { BpmnViewer } from "./BpmnViewer";
import { usePackDetail, usePackBpmn, usePackResolution } from "./queries";
import { elementLabel } from "@/lib/steps";
import type { Binding } from "@/api/types";
import type { HitlTaskMode } from "@/lib/hitl";

export function PackDetailPage() {
  const { packKey, version } = useParams();
  const { data: pack, isLoading, error } = usePackDetail(packKey, version);
  const { data: bpmn } = usePackBpmn(packKey, version);
  const { data: resolution } = usePackResolution(packKey, version);

  if (isLoading) return <div className="space-y-4"><Skeleton className="h-8 w-64" /><Skeleton className="h-64 w-full" /></div>;
  if (isConnectivityError(error)) return <ConnectivityState error={error} />;
  if (!pack) return <EmptyState title="Pack not found" />;

  const bindings = (pack.bindings ?? []) as Binding[];

  return (
    <>
      <div className="mb-4">
        <Link to="/registry" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" /> Registry
        </Link>
      </div>
      <PageHeader
        title={pack.title}
        description={`${pack.pack_key}@${pack.version}`}
        actions={<StatusBadge status={pack.status} />}
      />

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="diagram">Diagram</TabsTrigger>
          <TabsTrigger value="bpmn">BPMN XML</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-4">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <Card><CardContent className="p-4"><p className="text-2xl font-semibold tabular-nums">{bindings.length}</p><p className="text-xs text-muted-foreground">Steps</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-2xl font-semibold tabular-nums">{pack.triage_rules?.length ?? 0}</p><p className="text-xs text-muted-foreground">Triage rules</p></CardContent></Card>
            <Card><CardContent className="p-4"><p className="text-2xl font-semibold tabular-nums">{pack.requires_capabilities?.length ?? 0}</p><p className="text-xs text-muted-foreground">Capabilities</p></CardContent></Card>
          </div>

          <Card>
            <CardHeader><CardTitle>Bindings</CardTitle></CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Step</TableHead>
                    <TableHead>Kind</TableHead>
                    <TableHead>Executor</TableHead>
                    <TableHead>HITL</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {bindings.map((b) => {
                    const ex = b.executor as any;
                    const mode = b.hitl?.mode as string | undefined;
                    return (
                      <TableRow key={b.element_id}>
                        <TableCell>
                          <p className="font-medium">{elementLabel(b.element_id)}</p>
                          <p className="font-mono text-[10px] text-muted-foreground">{b.element_id}</p>
                        </TableCell>
                        <TableCell><Badge variant="outline">{b.element_kind}</Badge></TableCell>
                        <TableCell className="font-mono text-xs">
                          {ex?.type === "human" ? <span className="text-process">{ex.role}</span> : <span className="text-artifact">{ex?.capability}</span>}
                        </TableCell>
                        <TableCell>
                          {mode && mode !== "none" ? <ModeBadge mode={mode as HitlTaskMode} /> : <span className="text-xs text-muted-foreground">none</span>}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {resolution && (
            <Card>
              <CardHeader><CardTitle>Pinned resolution</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                <p className="text-xs text-muted-foreground">On activation every version range was pinned to the highest active version.</p>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Execution profile</span>
                  {(resolution.required_execution_profile ?? "common_subset") !== "common_subset" ? (
                    <Badge variant="process" className="text-[11px]" title={`Runs only on a runtime at the ${resolution.required_execution_profile} execution profile.`}>
                      requires {resolution.required_execution_profile} profile
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="text-[11px] text-muted-foreground" title="Runs on the default (common_subset) execution profile.">
                      common_subset
                    </Badge>
                  )}
                </div>
                <div>
                  <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">Capabilities</p>
                  <div className="flex flex-wrap gap-1">
                    {Object.entries(resolution.capabilities ?? {}).map(([k, v]) => (
                      <Badge key={k} variant="artifact" className="font-mono text-[10px]">{k} → {String(v)}</Badge>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">Artifacts</p>
                  <div className="flex flex-wrap gap-1">
                    {Object.entries(resolution.artifacts ?? {}).map(([k, v]) => (
                      <Badge key={k} variant="outline" className="font-mono text-[10px]">{k} → {String(v)}</Badge>
                    ))}
                  </div>
                </div>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="diagram">
          <Card><CardContent className="p-4"><BpmnViewer xml={bpmn} /></CardContent></Card>
        </TabsContent>

        <TabsContent value="bpmn">
          <Card>
            <CardContent className="p-0">
              <pre className="max-h-[500px] overflow-auto rounded-md p-4 text-xs">{bpmn ?? "Loading…"}</pre>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </>
  );
}
