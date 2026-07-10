import { useMemo } from "react";
import { Link } from "react-router-dom";
import { Clock, AlertTriangle, ArrowRight, Radio, CheckCircle2 } from "lucide-react";
import { PageHeader } from "@/app/AppShell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { IdMono, ReasonCodeBadge, EmptyState, LiveDot } from "@/components/primitives";
import { ConnectivityBanner } from "@/components/ConnectivityState";
import { isConnectivityError } from "@/api/client";
import { formatDateTime, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ProcessInstance, IngestionRecord } from "@/api/types";
import {
  useRecentActivity,
  useSessionEventCount,
  useNotificationsStatus,
  type ActivityEntry,
} from "@/app/NotificationsProvider";
import {
  pipelineCounts,
  waitStats,
  reasonTally,
  formatDuration,
  type PipelineCounts,
} from "./compute";
import { formatActivitySignal } from "./activity";
import {
  DASHBOARD_LIMIT,
  useDashboardExceptions,
  useDashboardIngestions,
  useDashboardInstances,
  useFailedInstances,
  useNoProcessIngestions,
  useOpenTasks,
} from "./queries";

type Tone = "neutral" | "attention" | "success" | "danger";

export function DashboardPage() {
  // The whole dashboard is client-side aggregation over the existing list
  // services — see ./compute. No dashboard-specific backend endpoint exists.
  const exceptions = useDashboardExceptions();
  const ingestions = useDashboardIngestions();
  const instances = useDashboardInstances();
  const failed = useFailedInstances();
  const noProcess = useNoProcessIngestions();
  const openTasks = useOpenTasks();

  const sseStatus = useNotificationsStatus();
  const activity = useRecentActivity();
  const eventsToday = useSessionEventCount();

  const errors = [exceptions, ingestions, instances, failed, noProcess, openTasks].map((q) => q.error);
  const connError = errors.find(isConnectivityError);

  const now = new Date();

  const counts = useMemo<PipelineCounts>(
    () => pipelineCounts(exceptions.data ?? [], ingestions.data ?? [], instances.data ?? [], now),
    // recompute when any source list changes; `now` intentionally re-read each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [exceptions.data, ingestions.data, instances.data],
  );

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const wait = useMemo(() => waitStats(openTasks.data ?? [], now), [openTasks.data]);
  const reasons = useMemo(() => reasonTally(exceptions.data ?? []), [exceptions.data]);

  const pipelineLoading = exceptions.isLoading || ingestions.isLoading || instances.isLoading;
  const truncated = [exceptions.data, ingestions.data, instances.data].some(
    (list) => (list?.length ?? 0) >= DASHBOARD_LIMIT,
  );

  const tiles: { key: keyof PipelineCounts; label: string; to: string; tone: Tone; sub?: string }[] = [
    { key: "raised", label: "Raised", to: "/exceptions", tone: "neutral" },
    { key: "ingested", label: "Ingested", to: "/exceptions", tone: "neutral" },
    { key: "dispatched", label: "Dispatched", to: "/exceptions", tone: "neutral" },
    { key: "running", label: "Running", to: "/instances", tone: "neutral" },
    { key: "waiting", label: "Waiting", to: "/instances", tone: "attention", sub: "on human" },
    { key: "completed", label: "Completed", to: "/instances", tone: "success" },
    { key: "failed", label: "Failed", to: "/instances", tone: "danger" },
    { key: "noProcess", label: "No process", to: "/exceptions", tone: "danger" },
  ];

  return (
    <>
      <PageHeader
        title="Exception Command Center"
        description={formatDateTime(now.toISOString())}
        badge={<LivePill status={sseStatus} count={eventsToday} />}
      />

      <ConnectivityBanner error={connError} />

      {/* ---- Today's pipeline ---- */}
      <section className="mb-6">
        <div className="mb-3">
          <h2 className="text-sm font-semibold">Today&apos;s pipeline</h2>
        </div>
        <div className="flex gap-3 overflow-x-auto pb-1">
          {tiles.map((t) => (
            <PipelineTile
              key={t.key}
              to={t.to}
              label={t.label}
              sub={t.sub}
              tone={t.tone}
              value={counts[t.key]}
              loading={pipelineLoading}
            />
          ))}
        </div>
        {truncated && (
          <p className="mt-2 text-xs text-muted-foreground">
            Showing recent {DASHBOARD_LIMIT} of each list — counts may under-report on a busy day.
          </p>
        )}
      </section>

      {/* ---- Waiting on human · Needs triage ---- */}
      <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <WaitingOnHuman
          count={wait.count}
          avgSeconds={wait.avgSeconds}
          oldestSeconds={wait.oldestSeconds}
          loading={openTasks.isLoading}
        />
        <NeedsTriage
          failed={failed.data ?? []}
          noProcess={noProcess.data ?? []}
          loading={failed.isLoading || noProcess.isLoading}
        />
      </div>

      {/* ---- Live activity · By reason code ---- */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_360px]">
        <LiveActivity activity={activity} status={sseStatus} />
        <ReasonCodes reasons={reasons} loading={exceptions.isLoading} />
      </div>
    </>
  );
}

/* --------------------------------- header --------------------------------- */

function LivePill({ status, count }: { status: string; count: number }) {
  const up = status === "up";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs",
        up ? "border-success/40 bg-success-muted/30" : "border-border bg-muted/40 text-muted-foreground",
      )}
    >
      {up ? (
        <LiveDot label="Live" />
      ) : (
        <span className="inline-flex items-center gap-1.5">
          <Radio className="size-3" /> Offline
        </span>
      )}
      <span className="text-muted-foreground">·</span>
      <span className="tabular-nums font-medium">{count}</span> events today
    </span>
  );
}

/* ------------------------------ pipeline tile ----------------------------- */

function PipelineTile({
  to,
  label,
  sub,
  tone,
  value,
  loading,
}: {
  to: string;
  label: string;
  sub?: string;
  tone: Tone;
  value: number;
  loading: boolean;
}) {
  const highlight = tone === "attention";
  const valueTone =
    tone === "success" ? "text-success" : tone === "danger" ? "text-danger" : "text-foreground";
  return (
    <Link
      to={to}
      className={cn(
        "min-w-[120px] shrink-0 rounded-lg border bg-surface p-4 transition-colors hover:border-border/80",
        highlight ? "border-attention/40 bg-attention-muted/30" : "border-border",
      )}
    >
      <div className="flex items-baseline gap-1.5">
        <span className={cn("text-sm font-medium", highlight ? "text-attention" : "text-muted-foreground")}>
          {label}
        </span>
        {sub && <span className="text-xs text-muted-foreground">{sub}</span>}
      </div>
      {loading ? (
        <Skeleton className="mt-1 h-9 w-12" />
      ) : (
        <p className={cn("mt-1 text-3xl font-semibold tabular-nums", valueTone)}>{value}</p>
      )}
    </Link>
  );
}

/* --------------------------- waiting on human ----------------------------- */

function WaitingOnHuman({
  count,
  avgSeconds,
  oldestSeconds,
  loading,
}: {
  count: number;
  avgSeconds: number | null;
  oldestSeconds: number | null;
  loading: boolean;
}) {
  return (
    <Card className="border-attention/40 bg-attention-muted/20">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-attention">
          <Clock className="size-4" /> Waiting on human
        </CardTitle>
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-16 w-full" />
        ) : (
          <div className="flex flex-wrap items-end gap-6">
            <p className="text-5xl font-semibold tabular-nums">{count}</p>
            <div className="space-y-1 text-sm">
              <p className="text-muted-foreground">
                Avg wait <span className="font-medium text-foreground">{formatDuration(avgSeconds)}</span>
              </p>
              <p className="text-muted-foreground">
                Oldest task{" "}
                <span className="font-medium text-foreground">{formatDuration(oldestSeconds)}</span>
              </p>
            </div>
          </div>
        )}
        <Button asChild className="mt-4">
          <Link to="/inbox">
            Open task inbox <ArrowRight className="size-4" />
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}

/* ------------------------------ needs triage ------------------------------ */

function NeedsTriage({
  failed,
  noProcess,
  loading,
}: {
  failed: ProcessInstance[];
  noProcess: IngestionRecord[];
  loading: boolean;
}) {
  const total = failed.length + noProcess.length;
  const rows = [
    ...failed.map((i) => ({
      key: `f-${i.process_instance_id}`,
      to: `/instances/${i.process_instance_id}`,
      id: i.process_instance_id,
      detail: i.last_error ?? i.outcome ?? "Failed",
    })),
    ...noProcess.map((i) => ({
      key: `n-${i.exception_id}`,
      to: `/exceptions/${i.exception_id}`,
      id: i.exception_id,
      detail: "No matching process",
    })),
  ];

  return (
    <Card className="border-danger/40 bg-danger-muted/10">
      <CardHeader className="flex-row items-center gap-2">
        <CardTitle className="flex items-center gap-2 text-danger">
          <AlertTriangle className="size-4" /> Needs triage
        </CardTitle>
        {!loading && <span className="text-2xl font-semibold tabular-nums text-danger">{total}</span>}
        <span className="text-xs text-muted-foreground">failed / no process</span>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="space-y-2">
            {Array.from({ length: 2 }).map((_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<CheckCircle2 className="size-6 text-success" />}
            title="Nothing to triage"
            description="No failed instances or unroutable exceptions."
          />
        ) : (
          <ul className="divide-y divide-border">
            {rows.slice(0, 6).map((r) => (
              <li key={r.key}>
                <Link
                  to={r.to}
                  className="flex items-center gap-3 rounded-md px-1 py-2 hover:bg-danger-muted/20"
                >
                  <IdMono value={r.id} className="text-foreground" />
                  <span className="min-w-0 flex-1 truncate text-sm text-danger" title={r.detail}>
                    {r.detail}
                  </span>
                  <ArrowRight className="size-3.5 shrink-0 text-muted-foreground" />
                </Link>
              </li>
            ))}
            {rows.length > 6 && (
              <li className="pt-2 text-xs text-muted-foreground">+ {rows.length - 6} more</li>
            )}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

/* ------------------------------ live activity ----------------------------- */

function LiveActivity({ activity, status }: { activity: ActivityEntry[]; status: string }) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2">
          {status === "up" && <LiveDot label="" />}
          Live activity
        </CardTitle>
        <span className="font-mono text-xs text-muted-foreground">SSE · notification-service</span>
      </CardHeader>
      <CardContent>
        {/*
          These lines come only from the thin SSE signals the notification-service
          pushes today. The design mock's per-capability "produced <Artifact>" and
          "Checkpoint written #N" lines are NOT available yet — they need new runtime
          events (activity_executed, checkpoint_written) + a widened SSE payload.
        */}
        {activity.length === 0 ? (
          <EmptyState
            icon={<Radio className="size-6" />}
            title="Waiting for activity"
            description="Live events appear here as the pipeline runs."
          />
        ) : (
          <ol className="max-h-[360px] space-y-1 overflow-y-auto">
            {activity.map((entry) => (
              <li
                key={entry.id}
                className="flex items-start gap-2 rounded-md px-1.5 py-1.5 hover:bg-accent/40"
              >
                <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-agent" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm">{formatActivitySignal(entry.signal)}</p>
                  <p className="text-xs text-muted-foreground">{receivedLabel(entry.receivedAt)}</p>
                </div>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}

/** "just now" for very recent receipts, else a relative timestamp. */
function receivedLabel(receivedAt: string): string {
  const ageMs = Date.now() - new Date(receivedAt).getTime();
  if (Number.isFinite(ageMs) && ageMs < 45_000) return "just now";
  return formatRelative(receivedAt);
}

/* ------------------------------ by reason code ---------------------------- */

function ReasonCodes({
  reasons,
  loading,
}: {
  reasons: { code: string; count: number }[];
  loading: boolean;
}) {
  const max = Math.max(1, ...reasons.map((r) => r.count));
  return (
    <Card>
      <CardHeader>
        <CardTitle>By reason code</CardTitle>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-6 w-full" />
            ))}
          </div>
        ) : reasons.length === 0 ? (
          <EmptyState title="No reason codes" description="No exceptions to tally yet." />
        ) : (
          <ul className="space-y-2.5">
            {reasons.map((r) => (
              <li key={r.code} className="flex items-center gap-3">
                <ReasonCodeBadge code={r.code} className="w-14 shrink-0 justify-center" />
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-process transition-all"
                    style={{ width: `${(r.count / max) * 100}%` }}
                  />
                </div>
                <span className="w-8 shrink-0 text-right text-sm tabular-nums text-muted-foreground">
                  {r.count}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
