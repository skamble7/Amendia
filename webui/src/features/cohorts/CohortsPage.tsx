import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Boxes, Plus } from "lucide-react";
import { PageHeader } from "@/app/AppShell";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";
import { LiveDot, EmptyState } from "@/components/primitives";
import { ConnectivityState } from "@/components/ConnectivityState";
import { isConnectivityError } from "@/api/client";
import { formatDateTime } from "@/lib/format";
import { useCohorts, useCohortDefinitions } from "./queries";
import { CohortStateChip, RollupBar } from "./cohortBits";

function Kpi({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: string; tone?: "ok" | "warn" }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
        <p className={`mt-1.5 text-2xl font-semibold ${tone === "ok" ? "text-success" : tone === "warn" ? "text-attention" : ""}`}>
          {value}
        </p>
        {sub && <p className="mt-0.5 text-[11px] text-muted-foreground">{sub}</p>}
      </CardContent>
    </Card>
  );
}

export function CohortsPage() {
  const navigate = useNavigate();
  const { data: list, isLoading, isFetching, error } = useCohorts();
  const { data: definitions } = useCohortDefinitions();

  const cohorts = useMemo(() => list?.cohorts ?? [], [list]);
  const kpis = useMemo(() => {
    const active = cohorts.filter((c) => c.state !== "closed");
    return {
      definitions: definitions?.length ?? 0,
      open: cohorts.filter((c) => c.state === "open").length,
      closing: cohorts.filter((c) => c.state === "closing").length,
      active: active.length,
      closed: cohorts.filter((c) => c.state === "closed").length,
      anomalies: cohorts.reduce((n, c) => n + (c.anomalies ?? 0), 0),
    };
  }, [cohorts, definitions]);

  return (
    <>
      <PageHeader
        title="Cohorts"
        description="Cross-system cases Amendia participates in — one row per cohort instance, keyed by correlation value."
        badge={isFetching ? <LiveDot /> : undefined}
        actions={
          <Button size="sm" onClick={() => navigate("/cohorts/new")}>
            <Plus className="size-4" /> New cohort
          </Button>
        }
      />

      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Definitions" value={kpis.definitions} sub="registered" />
        <Kpi label="Active cohorts" value={kpis.active} sub={`${kpis.open} open · ${kpis.closing} closing`} />
        <Kpi label="Closed" value={kpis.closed} sub="by orchestrator" tone="ok" />
        <Kpi label="Anomalies" value={kpis.anomalies} sub="late-join flags" tone={kpis.anomalies ? "warn" : undefined} />
      </div>

      {isConnectivityError(error) ? (
        <ConnectivityState error={error} />
      ) : (
        <div className="rounded-lg border border-border bg-surface">
          {isLoading ? (
            <div className="space-y-2 p-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}</div>
          ) : cohorts.length === 0 ? (
            <EmptyState
              icon={<Boxes className="size-6" />}
              title="No cohorts yet"
              description="A cohort opens when the first member segment of a cross-system case spawns. Register a cohort definition and assign packs to start grouping."
              action={<Button size="sm" variant="outline" onClick={() => navigate("/cohorts/new")}><Plus className="size-4" /> New cohort</Button>}
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Correlation</TableHead>
                  <TableHead>Cohort</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead>Segments (Amendia)</TableHead>
                  <TableHead>Opened</TableHead>
                  <TableHead>Closed</TableHead>
                  <TableHead>Outcome</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {cohorts.map((c) => (
                  <TableRow
                    key={c.cohort_instance_id}
                    className="cursor-pointer"
                    tabIndex={0}
                    onClick={() => navigate(`/cohorts/${c.cohort_instance_id}`)}
                    onKeyDown={(e) => e.key === "Enter" && navigate(`/cohorts/${c.cohort_instance_id}`)}
                  >
                    <TableCell className="font-mono text-sm text-foreground">{c.correlation_value || "—"}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{c.cohort_def_id}</TableCell>
                    <TableCell><CohortStateChip state={c.state} /></TableCell>
                    <TableCell><RollupBar rollup={c.rollup} anomalies={c.anomalies} /></TableCell>
                    <TableCell className="text-xs text-muted-foreground">{formatDateTime(c.opened_at)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{c.closed_at ? formatDateTime(c.closed_at) : "—"}</TableCell>
                    <TableCell className="text-sm">{c.outcome ? <span className="text-agent">{c.outcome}</span> : <span className="text-muted-foreground">—</span>}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      )}

      {cohorts.some((c) => c.correlation_value) && (
        <div className="mt-3 flex flex-wrap gap-4 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5"><i className="size-2.5 rounded-[3px] bg-agent" /> open — members accumulating</span>
          <span className="inline-flex items-center gap-1.5"><i className="size-2.5 rounded-[3px] bg-attention" /> closing — orchestrator signalled end, a member still running</span>
          <span className="inline-flex items-center gap-1.5"><i className="size-2.5 rounded-[3px] bg-success" /> closed — drained, outcome from orchestrator</span>
        </div>
      )}
    </>
  );
}
