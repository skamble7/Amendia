import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, Pencil, Loader2, RotateCcw } from "lucide-react";
import { PageHeader } from "@/app/AppShell";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { ModeBadge } from "@/components/primitives";
import { EmptyState } from "@/components/primitives";
import { ConnectivityState } from "@/components/ConnectivityState";
import { ApiError, isConnectivityError } from "@/api/client";
import { editPack, rollbackPack } from "@/api/services/registry";
import { StatusBadge } from "./RegistryPage";
import { BpmnViewer } from "./BpmnViewer";
import { usePackDetail, usePackBpmn, usePackResolution, usePackVersions } from "./queries";
import { elementLabel } from "@/lib/steps";
import type { Binding, ProcessPackManifest } from "@/api/types";
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
        actions={
          <div className="flex items-center gap-2">
            <StatusBadge status={pack.status} />
            {pack.status === "active" && <EditPackControl packKey={pack.pack_key} />}
          </div>
        }
      />

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="diagram">Diagram</TabsTrigger>
          <TabsTrigger value="bpmn">BPMN XML</TabsTrigger>
          <TabsTrigger value="versions">Versions</TabsTrigger>
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

        <TabsContent value="versions">
          <VersionsTab packKey={pack.pack_key} currentVersion={pack.version} />
        </TabsContent>
      </Tabs>
    </>
  );
}

// ADR-056: Edit an active pack's config → clone-edit session at a bumped version → stepped review in edit mode.
function EditPackControl({ packKey }: { packKey: string }) {
  const navigate = useNavigate();
  const [bump, setBump] = useState<"minor" | "major">("minor");
  const edit = useMutation({
    mutationFn: () => editPack(packKey, bump),
    onSuccess: (s) => navigate(`/registry/onboard/${s.session_id}?mode=edit`),
    onError: (e) => toast.error(e instanceof ApiError ? e.detailText : "Couldn't open the editor."),
  });
  return (
    <div className="flex items-center gap-1">
      <select
        aria-label="version bump" value={bump} onChange={(e) => setBump(e.target.value as "minor" | "major")}
        className="h-8 rounded-md border border-input bg-transparent px-2 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <option value="minor">minor</option>
        <option value="major">major</option>
      </select>
      <Button size="sm" className="gap-1" disabled={edit.isPending} onClick={() => edit.mutate()}>
        {edit.isPending ? <Loader2 className="size-4 animate-spin" /> : <Pencil className="size-3.5" />} Edit config
      </Button>
    </div>
  );
}

// ADR-056: per-pack version history + rollback (make a deprecated version live again).
function VersionsTab({ packKey, currentVersion }: { packKey: string; currentVersion: string }) {
  const { data: versions } = usePackVersions(packKey);
  const qc = useQueryClient();
  const rollback = useMutation({
    mutationFn: (to: string) => rollbackPack(packKey, to),
    onSuccess: (m) => {
      toast.success(`${m.pack_key}@${m.version} is live again — new work routes to it.`);
      qc.invalidateQueries({ queryKey: ["pack-versions", packKey] });
      qc.invalidateQueries({ queryKey: ["pack", packKey] });
      qc.invalidateQueries({ queryKey: ["packs"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.detailText : "Rollback failed."),
  });
  const sorted = [...(versions ?? [])].sort((a, b) => b.version.localeCompare(a.version, undefined, { numeric: true }));

  return (
    <Card>
      <CardHeader><CardTitle>Version history</CardTitle></CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Version</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Updated</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((m: ProcessPackManifest) => (
              <TableRow key={m.version} className={m.version === currentVersion ? "bg-surface/40" : undefined}>
                <TableCell className="font-mono text-xs">
                  {m.version}{m.status === "active" && <Badge variant="success" className="ml-2 text-[10px]">live</Badge>}
                </TableCell>
                <TableCell><StatusBadge status={m.status} /></TableCell>
                <TableCell className="text-xs text-muted-foreground">{(m.updated_at ?? m.created_at ?? "").slice(0, 10)}</TableCell>
                <TableCell className="text-right">
                  {m.status === "deprecated" && (
                    <Button size="sm" variant="outline" className="gap-1" disabled={rollback.isPending}
                      onClick={() => { if (window.confirm(`Make ${packKey}@${m.version} live again? The current live version will be deprecated.`)) rollback.mutate(m.version); }}>
                      <RotateCcw className="size-3.5" /> Make live
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
