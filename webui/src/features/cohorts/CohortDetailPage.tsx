import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, LiveDot } from "@/components/primitives";
import { ConnectivityState } from "@/components/ConnectivityState";
import { isConnectivityError } from "@/api/client";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useCohort, useCohortByCorrelation } from "./queries";
import { CohortStateChip } from "./cohortBits";
import { MemberDiagram } from "./MemberDiagram";
import type { CohortDetailOut, CohortEventOut, CohortState } from "@/api/types";

function Kpi({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: string; tone?: "ok" | "run" | "zero" | "warn" }) {
  const cls = tone === "ok" ? "text-success" : tone === "run" ? "text-agent" : tone === "warn" ? "text-attention" : tone === "zero" ? "text-muted-foreground" : "";
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
        <p className={cn("mt-1.5 text-2xl font-semibold", cls)}>{value}</p>
        {sub && <p className="mt-0.5 text-[11px] text-muted-foreground">{sub}</p>}
      </CardContent>
    </Card>
  );
}

const OP_TONE: Record<string, string> = {
  opened: "border-agent text-agent",
  member_joined: "border-artifact text-artifact",
  late_join: "border-attention text-attention",
  closing: "border-attention text-attention",
  closed: "border-success text-success",
};

function LifecycleMachine({ state }: { state: CohortState }) {
  const order: CohortState[] = ["open", "closing", "closed"];
  const idx = order.indexOf(state);
  return (
    <div className="flex items-center">
      {order.map((s, i) => (
        <div key={s} className="flex items-center">
          <span
            className={cn(
              "rounded-full border px-3 py-1 text-xs",
              i < idx && "border-transparent bg-success-muted text-success",
              i === idx && "border-attention bg-attention-muted text-attention",
              i > idx && "border-border bg-muted text-muted-foreground",
            )}
          >
            {s}
          </span>
          {i < order.length - 1 && <span className={cn("h-0.5 w-6", i < idx ? "bg-success/40" : "bg-border")} />}
        </div>
      ))}
    </div>
  );
}

function EventStream({ events }: { events: CohortEventOut[] }) {
  if (events.length === 0) return <p className="text-sm text-muted-foreground">No lifecycle events yet.</p>;
  return (
    <ol className="relative space-y-3 pl-5">
      <span className="absolute left-[6px] top-1 bottom-1 w-0.5 bg-border" aria-hidden />
      {events.map((e, i) => (
        <li key={i} className="relative">
          <span className={cn("absolute -left-5 top-1 size-3 rounded-full border-2 bg-surface", OP_TONE[e.op] ?? "border-border")} aria-hidden />
          <div className="flex items-baseline justify-between gap-3">
            <span className={cn("font-mono text-xs", (OP_TONE[e.op] ?? "").split(" ")[1])}>{e.op}</span>
            <span className="font-mono text-[11px] text-muted-foreground">{formatDateTime(e.at)}</span>
          </div>
          {e.detail && <p className="text-[11px] text-muted-foreground">{e.detail}</p>}
        </li>
      ))}
    </ol>
  );
}

function CohortDetailContent({ cohort }: { cohort: CohortDetailOut }) {
  const navigate = useNavigate();
  const inFlight = cohort.rollup.running;

  return (
    <>
      <div className="mb-4">
        <Link to="/cohorts" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" /> Cohorts
        </Link>
      </div>

      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h1 className="font-mono text-xl font-semibold tracking-tight">{cohort.cohort_instance_id}</h1>
          <p className="text-sm text-muted-foreground">
            <span className="text-foreground">{cohort.cohort_def_id}</span> · correlation{" "}
            <span className="font-mono text-foreground">{cohort.correlation_value}</span> · {cohort.member_count} Amendia{" "}
            {cohort.member_count === 1 ? "segment" : "segments"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => navigate("/cohorts/new")}>Manage membership</Button>
          <CohortStateChip state={cohort.state} />
        </div>
      </div>

      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Kpi label="Members" value={cohort.member_count} sub="Amendia segments" />
        <Kpi label="Completed" value={cohort.rollup.done} sub="terminal" tone={cohort.rollup.done ? "ok" : "zero"} />
        <Kpi label="Running" value={cohort.rollup.running} sub="in flight" tone={cohort.rollup.running ? "run" : "zero"} />
        <Kpi label="Failed" value={cohort.rollup.failed} sub={cohort.rollup.failed ? "terminal" : "none"} tone={cohort.rollup.failed ? "warn" : "zero"} />
        <Kpi label="Anomalies" value={cohort.anomalies} sub="late-join" tone={cohort.anomalies ? "warn" : "zero"} />
      </div>

      {/* The hero: per-member BPMN diagrams with live highlighting */}
      <Card className="mb-4">
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Member processes — live state</CardTitle>
          <span className="text-xs text-muted-foreground">
            {cohort.roster.length} {cohort.roster.length === 1 ? "segment" : "segments"} · each highlighted to its own execution (ADR-062)
          </span>
        </CardHeader>
        <CardContent>
          {cohort.roster.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">No members have joined this cohort yet.</p>
          ) : (
            cohort.roster.map((m) => <MemberDiagram key={m.process_instance_id} member={m} />)
          )}
          <div className="mt-2 flex flex-wrap gap-4 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1.5"><i className="size-2.5 rounded-[3px] border border-success bg-success/20" /> executed (done)</span>
            <span className="inline-flex items-center gap-1.5"><i className="size-2.5 rounded-[3px] border border-agent bg-agent/20" /> current (waiting)</span>
            <span className="inline-flex items-center gap-1.5"><i className="size-2.5 rounded-[3px] border border-border bg-muted" /> not taken (pending)</span>
            <span className="inline-flex items-center gap-1.5"><i className="size-2.5 rounded-[3px] border border-danger bg-danger/20" /> failed</span>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.15fr_1fr]">
        <Card>
          <CardContent className="p-4">
            <p className="rounded-md border border-dashed border-border bg-surface/50 p-3 text-sm text-muted-foreground">
              <span className="font-medium text-foreground">Amendia observes {cohort.member_count} of its own segments.</span>{" "}
              The wider process is orchestrated externally (e.g. Pega) and its other segments aren't visible here — by
              design, Amendia executes only its assigned segments and never terminates a running one. The orchestrator's
              close outcome is the authority on overall completion.
              {cohort.state === "closing" && inFlight > 0 && (
                <> The orchestrator has signalled end-of-process, but the cohort stays <span className="text-attention">closing</span> until {inFlight} running {inFlight === 1 ? "segment finishes" : "segments finish"}.</>
              )}
            </p>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>Lifecycle</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <LifecycleMachine state={cohort.state} />
              <div>
                <p className="mb-2 text-[11px] uppercase tracking-wide text-muted-foreground">CohortLifecycleEvent stream</p>
                <EventStream events={cohort.events} />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Close</CardTitle></CardHeader>
            <CardContent className="text-sm">
              <Row k="Close signal" v={cohort.close.signalled ? "received from orchestrator" : "not yet signalled"} />
              <Row k="Correlation handle" v={<span className="font-mono text-xs">{cohort.correlation_value}</span>} />
              <Row k="Reported outcome" v={cohort.outcome ? <span className="text-agent">{cohort.outcome}</span> : "—"} />
              <Row k="Cohort state" v={<span className={cn(cohort.state === "closing" && "text-attention", cohort.state === "closed" && "text-success")}>{cohort.state}{cohort.state === "closing" && inFlight > 0 ? ` — ${inFlight} running` : ""}</span>} />
              {cohort.close.late_joins > 0 && <Row k="Late joins" v={<span className="text-attention">{cohort.close.late_joins}</span>} />}
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 border-b border-border py-2 last:border-none">
      <span className="text-muted-foreground">{k}</span>
      <span className="text-right">{v}</span>
    </div>
  );
}

export function CohortDetailPage() {
  const { cohortId, correlationValue } = useParams();
  const byId = useCohort(correlationValue ? undefined : cohortId);
  const byValue = useCohortByCorrelation(correlationValue);
  const { data: cohort, isLoading, error } = correlationValue ? byValue : byId;

  if (isConnectivityError(error)) return <ConnectivityState error={error} />;
  if (isLoading) {
    return <div className="space-y-4"><Skeleton className="h-8 w-64" /><Skeleton className="h-64 w-full" /></div>;
  }
  if (!cohort) {
    return (
      <>
        <div className="mb-4">
          <Link to="/cohorts" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
            <ArrowLeft className="size-4" /> Cohorts
          </Link>
        </div>
        <EmptyState title="Cohort not found" description="It may have been pruned, or GLEA hasn't observed any events for it yet." />
      </>
    );
  }
  return (
    <>
      {byId.isFetching && <div className="mb-2 flex justify-end"><LiveDot /></div>}
      <CohortDetailContent cohort={cohort} />
    </>
  );
}
