import { useMemo } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Boxes, Network, Plus } from "lucide-react";
import { PageHeader } from "@/app/AppShell";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";
import { LiveDot, EmptyState } from "@/components/primitives";
import { ConnectivityState } from "@/components/ConnectivityState";
import { isConnectivityError } from "@/api/client";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useActivePacks, useCohorts, useCohortDefinitions } from "./queries";
import { CohortStateChip, RollupBar, SlaBadges } from "./cohortBits";
import { closeMatch, membersOf, unassignedPacks } from "./membership";
import type { CohortDefinition, CohortListEntry } from "@/api/types";

/** Reused KPI tile. */
export function Kpi({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: string; tone?: "ok" | "warn" }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
        <p className={cn("mt-1.5 text-2xl font-semibold", tone === "ok" && "text-success", tone === "warn" && "text-attention")}>
          {value}
        </p>
        {sub && <p className="mt-0.5 text-[11px] text-muted-foreground">{sub}</p>}
      </CardContent>
    </Card>
  );
}

type Tab = "instances" | "definitions";

function SegmentedTabs({ tab, onTab }: { tab: Tab; onTab: (t: Tab) => void }) {
  return (
    <div className="mb-5 inline-flex rounded-lg border border-border bg-surface p-0.5" role="tablist">
      {(["instances", "definitions"] as const).map((t) => (
        <button
          key={t}
          role="tab"
          aria-selected={tab === t}
          onClick={() => onTab(t)}
          className={cn(
            "rounded-md px-3.5 py-1.5 text-sm font-medium capitalize transition-colors",
            tab === t ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {t}
        </button>
      ))}
    </div>
  );
}

export function CohortsPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get("tab") === "definitions" ? "definitions" : "instances";
  const setTab = (t: Tab) => setParams(t === "instances" ? {} : { tab: t }, { replace: true });

  const cohortsQ = useCohorts();
  const { data: definitions } = useCohortDefinitions();
  const cohorts = useMemo(() => cohortsQ.data?.cohorts ?? [], [cohortsQ.data]);

  return (
    <>
      <PageHeader
        title="Cohorts"
        description={
          tab === "instances"
            ? "Cross-system cases Amendia participates in — one row per cohort instance, keyed by correlation value."
            : "Cohort definitions — the design-time config an owner maintains, including which packs are members."
        }
        badge={cohortsQ.isFetching ? <LiveDot /> : undefined}
        actions={
          tab === "definitions" ? (
            <Button size="sm" onClick={() => navigate("/cohorts/new")}>
              <Plus className="size-4" /> New cohort
            </Button>
          ) : undefined
        }
      />

      <SegmentedTabs tab={tab} onTab={setTab} />

      {tab === "instances" ? (
        <InstancesTab
          cohorts={cohorts}
          definitions={definitions}
          isLoading={cohortsQ.isLoading}
          error={cohortsQ.error}
          navigate={navigate}
        />
      ) : (
        <DefinitionsTab definitions={definitions} cohorts={cohorts} navigate={navigate} />
      )}
    </>
  );
}

// --------------------------------------------------------------------------- #
// Instances tab (unchanged observability list + KPIs)
// --------------------------------------------------------------------------- #
function InstancesTab({
  cohorts,
  definitions,
  isLoading,
  error,
  navigate,
}: {
  cohorts: CohortListEntry[];
  definitions: CohortDefinition[] | undefined;
  isLoading: boolean;
  error: unknown;
  navigate: (to: string) => void;
}) {
  const kpis = {
    definitions: definitions?.length ?? 0,
    open: cohorts.filter((c) => c.state === "open").length,
    closing: cohorts.filter((c) => c.state === "closing").length,
    active: cohorts.filter((c) => c.state !== "closed").length,
    closed: cohorts.filter((c) => c.state === "closed").length,
    anomalies: cohorts.reduce((n, c) => n + (c.anomalies ?? 0), 0),
  };

  if (isConnectivityError(error)) return <ConnectivityState error={error} />;

  return (
    <>
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Definitions" value={kpis.definitions} sub="registered" />
        <Kpi label="Active cohorts" value={kpis.active} sub={`${kpis.open} open · ${kpis.closing} closing`} />
        <Kpi label="Closed" value={kpis.closed} sub="by orchestrator" tone="ok" />
        <Kpi label="Anomalies" value={kpis.anomalies} sub="late-join flags" tone={kpis.anomalies ? "warn" : undefined} />
      </div>

      <div className="rounded-lg border border-border bg-surface">
        {isLoading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}</div>
        ) : cohorts.length === 0 ? (
          <EmptyState
            icon={<Boxes className="size-6" />}
            title="No cohorts yet"
            description="A cohort opens when the first member segment of a cross-system case spawns. Register a cohort definition and assign packs to start grouping."
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
                  <TableCell className="font-mono text-sm text-foreground">
                    <span className="inline-flex items-center gap-2">{c.correlation_value || "—"}<SlaBadges breaches={c.sla_breaches} atRisk={c.sla_at_risk} /></span>
                  </TableCell>
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

// --------------------------------------------------------------------------- #
// Definitions tab (new — design-time config; membership managed on the detail)
// --------------------------------------------------------------------------- #
function DefinitionsTab({
  definitions,
  cohorts,
  navigate,
}: {
  definitions: CohortDefinition[] | undefined;
  cohorts: CohortListEntry[];
  navigate: (to: string) => void;
}) {
  const { data: packs, isLoading } = useActivePacks();

  const instancesByDef = useMemo(() => {
    const m = new Map<string, { total: number; closed: number }>();
    for (const c of cohorts) {
      const e = m.get(c.cohort_def_id) ?? { total: 0, closed: 0 };
      e.total += 1;
      if (c.state === "closed") e.closed += 1;
      m.set(c.cohort_def_id, e);
    }
    return m;
  }, [cohorts]);

  const membersTotal = (packs ?? []).filter((p) => p.cohort_membership).length;
  const unassigned = unassignedPacks(packs).length;

  return (
    <>
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Definitions" value={definitions?.length ?? 0} sub="registered" />
        <Kpi label="Members total" value={membersTotal} sub="packs assigned" />
        <Kpi label="Instances" value={cohorts.length} sub="observed" />
        <Kpi label="Packs unassigned" value={unassigned} sub="active, no cohort" />
      </div>

      <div className="rounded-lg border border-border bg-surface">
        {definitions == null ? (
          <div className="space-y-2 p-4">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}</div>
        ) : definitions.length === 0 ? (
          <EmptyState
            icon={<Network className="size-6" />}
            title="No cohort definitions yet"
            description="A definition declares the correlation contract + the external close message, and which packs are members. Register one to start grouping segments."
            action={<Button size="sm" variant="outline" onClick={() => navigate("/cohorts/new")}><Plus className="size-4" /> New cohort</Button>}
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Cohort id</TableHead>
                <TableHead>Display name</TableHead>
                <TableHead>Members</TableHead>
                <TableHead>Close match</TableHead>
                <TableHead>Instances</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {definitions.map((d) => {
                const members = isLoading ? null : membersOf(d, packs).length;
                const inst = instancesByDef.get(d.cohort_def_id) ?? { total: 0, closed: 0 };
                return (
                  <TableRow
                    key={d.cohort_def_id}
                    className="cursor-pointer"
                    tabIndex={0}
                    onClick={() => navigate(`/cohorts/definitions/${d.cohort_def_id}`)}
                    onKeyDown={(e) => e.key === "Enter" && navigate(`/cohorts/definitions/${d.cohort_def_id}`)}
                  >
                    <TableCell className="font-mono text-sm text-foreground">{d.cohort_def_id}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{d.display_name || "—"}</TableCell>
                    <TableCell className="text-sm">{members == null ? <Skeleton className="h-4 w-6" /> : members}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{closeMatch(d)}</TableCell>
                    <TableCell className="text-sm">
                      {inst.total}
                      {inst.closed > 0 && <span className="text-muted-foreground"> · {inst.closed} closed</span>}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" variant="outline" onClick={(e) => { e.stopPropagation(); navigate(`/cohorts/definitions/${d.cohort_def_id}`); }}>
                        Manage
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </div>
    </>
  );
}
