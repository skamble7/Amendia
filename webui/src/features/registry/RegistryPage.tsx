import { Link, useNavigate } from "react-router-dom";
import { Plus, ChevronRight } from "lucide-react";
import { PageHeader } from "@/app/AppShell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/primitives";
import { ConnectivityState } from "@/components/ConnectivityState";
import { isConnectivityError } from "@/api/client";
import { statusMeta, REGISTRY_STATUS } from "@/lib/status";
import { usePacks } from "./queries";

// ADR-060: capabilities & artifact schemas are OWNED by a pack version — there is no global catalog. This page
// is the pack list; a pack's owned capabilities/schemas live on its detail page (see PackDetailPage).
export function RegistryPage() {
  const navigate = useNavigate();
  return (
    <>
      <PageHeader
        title="Registry"
        description="Process packs. Each pack owns its capabilities and artifact schemas."
        actions={
          <Button onClick={() => navigate("/registry/onboard")}>
            <Plus className="size-4" /> Onboard pack
          </Button>
        }
      />
      <PacksCatalog />
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

function CatalogSkeleton() {
  return <div className="grid grid-cols-1 gap-3 md:grid-cols-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-28 w-full" />)}</div>;
}

export { StatusBadge };
