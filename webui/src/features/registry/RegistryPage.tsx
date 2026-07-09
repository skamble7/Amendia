import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus, ChevronRight, ChevronDown } from "lucide-react";
import { PageHeader } from "@/app/AppShell";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { SideEffectBadge, EmptyState } from "@/components/primitives";
import { ConnectivityState } from "@/components/ConnectivityState";
import { isConnectivityError } from "@/api/client";
import { statusMeta, REGISTRY_STATUS } from "@/lib/status";
import { SchemaTree } from "./SchemaTree";
import { usePacks, useCapabilities, useArtifactSchemas } from "./queries";
import type { JsonSchema } from "@/components/artifact/schema";
import type { CapabilityDescriptor } from "@/api/types";

export function RegistryPage() {
  const navigate = useNavigate();
  return (
    <>
      <PageHeader
        title="Registry"
        description="Process packs, capabilities, and artifact schemas."
        actions={
          <Button onClick={() => navigate("/registry/onboard")}>
            <Plus className="size-4" /> Onboard pack
          </Button>
        }
      />
      <Tabs defaultValue="processes">
        <TabsList>
          <TabsTrigger value="processes">Processes</TabsTrigger>
          <TabsTrigger value="capabilities">Capabilities</TabsTrigger>
          <TabsTrigger value="schemas">Schemas</TabsTrigger>
        </TabsList>
        <TabsContent value="processes"><PacksCatalog /></TabsContent>
        <TabsContent value="capabilities"><CapabilitiesCatalog /></TabsContent>
        <TabsContent value="schemas"><SchemasCatalog /></TabsContent>
      </Tabs>
    </>
  );
}

function StatusBadge({ status }: { status: string }) {
  const m = statusMeta(REGISTRY_STATUS, status);
  return <Badge variant={m.variant}>{m.label}</Badge>;
}

function PacksCatalog() {
  const { data: packs, isLoading, error } = usePacks();
  if (isConnectivityError(error)) return <ConnectivityState error={error} />;
  if (isLoading) return <CatalogSkeleton />;
  if (!packs?.length) return <EmptyState title="No packs" description="Onboard a process pack to get started." />;
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {packs.map((p) => (
        <Link key={`${p.pack_key}@${p.version}`} to={`/registry/packs/${p.pack_key}/${p.version}`}>
          <Card className="h-full transition-colors hover:border-border/80">
            <CardContent className="p-4">
              <div className="mb-2 flex items-start justify-between gap-2">
                <div>
                  <p className="font-medium">{p.title}</p>
                  <p className="font-mono text-xs text-muted-foreground">{p.pack_key}@{p.version}</p>
                </div>
                <StatusBadge status={p.status} />
              </div>
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <span>{p.bindings?.length ?? 0} steps</span>
                <span>{p.triage_rules?.length ?? 0} triage rules</span>
                <ChevronRight className="ml-auto size-4" />
              </div>
            </CardContent>
          </Card>
        </Link>
      ))}
    </div>
  );
}

function CapabilitiesCatalog() {
  const { data: caps, isLoading, error } = useCapabilities();
  if (isConnectivityError(error)) return <ConnectivityState error={error} />;
  if (isLoading) return <CatalogSkeleton />;
  if (!caps?.length) return <EmptyState title="No capabilities" />;
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {caps.map((c) => <CapabilityCard key={`${c.capability_id}@${c.version}`} cap={c} />)}
    </div>
  );
}

function CapabilityCard({ cap }: { cap: CapabilityDescriptor }) {
  const minHitl = (cap as any).constraints?.min_hitl_mode as string | undefined;
  return (
    <Card>
      <CardContent className="space-y-2 p-4">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="font-medium">{cap.title}</p>
            <p className="font-mono text-xs text-muted-foreground">{cap.capability_id}@{cap.version}</p>
          </div>
          <Badge variant="agent">{cap.kind}</Badge>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <SideEffectBadge sideEffect={(cap as any).side_effect} />
          {minHitl && minHitl !== "none" && <Badge variant="attention">min HITL: {minHitl.replace(/_/g, " ")}</Badge>}
        </div>
        <div className="flex flex-wrap gap-1 text-xs">
          {((cap as any).inputs ?? []).map((io: any) => (
            <Badge key={`in-${io.name}`} variant="outline" className="font-mono text-[10px]">↓ {io.schema}</Badge>
          ))}
          {((cap as any).outputs ?? []).map((io: any) => (
            <Badge key={`out-${io.name}`} variant="artifact" className="font-mono text-[10px]">↑ {io.schema}</Badge>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function SchemasCatalog() {
  const { data: schemas, isLoading, error } = useArtifactSchemas();
  const [open, setOpen] = useState<string | null>(null);
  if (isConnectivityError(error)) return <ConnectivityState error={error} />;
  if (isLoading) return <CatalogSkeleton />;
  if (!schemas?.length) return <EmptyState title="No artifact schemas" />;
  return (
    <div className="space-y-2">
      {schemas.map((s) => {
        const id = `${s.artifact_key}@${s.version}`;
        const isOpen = open === id;
        return (
          <Card key={id}>
            <button className="flex w-full items-center gap-3 p-4 text-left" onClick={() => setOpen(isOpen ? null : id)}>
              {isOpen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
              <div className="flex-1">
                <p className="font-medium">{s.title}</p>
                <p className="font-mono text-xs text-muted-foreground">{s.artifact_key}@{s.version}</p>
              </div>
              <StatusBadge status={(s as any).status ?? "active"} />
            </button>
            {isOpen && (
              <CardContent className="border-t border-border pt-4">
                <SchemaTree schema={(s.json_schema ?? {}) as JsonSchema} />
              </CardContent>
            )}
          </Card>
        );
      })}
    </div>
  );
}

function CatalogSkeleton() {
  return <div className="grid grid-cols-1 gap-3 md:grid-cols-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-28 w-full" />)}</div>;
}

export { StatusBadge };
