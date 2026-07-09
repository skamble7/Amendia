import { useMemo } from "react";
import { Link } from "react-router-dom";
import { Inbox, AlertTriangle, CheckCircle2, Workflow, ArrowRight } from "lucide-react";
import { PageHeader } from "@/app/AppShell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusChip, IdMono, ModeBadge, LiveDot, ActorAvatar } from "@/components/primitives";
import { ConnectivityBanner } from "@/components/ConnectivityState";
import { isConnectivityError } from "@/api/client";
import { formatRelative } from "@/lib/format";
import { useIngestions } from "@/features/exceptions/queries";
import { useInstances } from "@/features/instances/queries";
import { useInboxTasks } from "@/features/inbox/queries";
import { cn } from "@/lib/utils";
import type { HitlTaskMode } from "@/lib/hitl";

// # backend-aggregation: these counts are computed client-side from list endpoints.
// A dedicated stats endpoint (e.g. GET /stats/pipeline) would remove the N-list fan-out.
function count<T>(items: T[] | undefined, pred: (t: T) => boolean): number {
  return (items ?? []).filter(pred).length;
}

export function DashboardPage() {
  const { data: ingestions, isLoading: li, error: ingError } = useIngestions();
  const { data: instances, isLoading: lin, error: instError } = useInstances();
  const { data: openTasks, isFetching, error: taskError } = useInboxTasks({ status: "open" });
  const connError = [ingError, instError, taskError].find(isConnectivityError);

  const funnel = useMemo(() => {
    const ing = ingestions ?? [];
    return [
      { label: "Received", value: ing.length, to: "/exceptions" },
      { label: "Dispatched", value: count(ing, (i) => ["dispatched", "accepted"].includes(i.status as string)), to: "/exceptions" },
      { label: "Accepted", value: count(ing, (i) => i.status === "accepted"), to: "/exceptions" },
      { label: "Running", value: count(instances, (i) => ["running", "waiting_hitl"].includes(i.status as string)), to: "/instances" },
      { label: "Completed", value: count(instances, (i) => i.status === "completed"), to: "/instances" },
    ];
  }, [ingestions, instances]);

  const failed = count(instances, (i) => i.status === "failed");
  const noProcess = count(ingestions, (i) => i.status === "no_process");
  const openCount = openTasks?.length ?? 0;
  const maxFunnel = Math.max(1, ...funnel.map((f) => f.value));

  const activity = useMemo(() => {
    const items = [
      ...(instances ?? []).map((i) => ({ kind: "instance" as const, id: i.process_instance_id, status: i.status, at: i.updated_at, exc: i.exception_id })),
    ];
    return items.sort((a, b) => (b.at ?? "").localeCompare(a.at ?? "")).slice(0, 8);
  }, [instances]);

  const loading = li || lin;

  return (
    <>
      <PageHeader title="Dashboard" description="Exception pipeline at a glance." badge={isFetching ? <LiveDot /> : undefined} />

      <ConnectivityBanner error={connError} />

      {/* Headline tiles */}
      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          to="/inbox"
          tone="attention"
          icon={<Inbox className="size-5" />}
          label="Waiting on human"
          value={openCount}
          hint={openCount ? "Open decision gates" : "Inbox clear"}
          loading={loading}
        />
        <StatTile to="/instances?status=running" tone="agent" icon={<Workflow className="size-5" />} label="Active instances" value={count(instances, (i) => ["running", "waiting_hitl"].includes(i.status as string))} loading={loading} />
        <StatTile to="/instances?status=completed" tone="success" icon={<CheckCircle2 className="size-5" />} label="Completed" value={count(instances, (i) => i.status === "completed")} loading={loading} />
        <StatTile to="/exceptions" tone="danger" icon={<AlertTriangle className="size-5" />} label="Failed / no process" value={failed + noProcess} hint={failed + noProcess ? "Needs attention" : "All clear"} loading={loading} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_360px]">
        {/* Funnel */}
        <Card>
          <CardHeader><CardTitle>Pipeline</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {loading ? (
              Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-8 w-full" />)
            ) : (
              funnel.map((f) => (
                <Link key={f.label} to={f.to} className="block">
                  <div className="mb-1 flex items-center justify-between text-sm">
                    <span>{f.label}</span>
                    <span className="tabular-nums font-medium">{f.value}</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-muted">
                    <div className="h-full rounded-full bg-agent transition-all" style={{ width: `${(f.value / maxFunnel) * 100}%` }} />
                  </div>
                </Link>
              ))
            )}
          </CardContent>
        </Card>

        {/* Activity feed */}
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>Activity</CardTitle>
            <LiveDot />
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="space-y-2">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}</div>
            ) : activity.length === 0 ? (
              <p className="text-sm text-muted-foreground">No recent activity.</p>
            ) : (
              <ol className="space-y-2.5">
                {activity.map((a) => (
                  <li key={a.id}>
                    <Link to={`/instances/${a.id}`} className="flex items-center gap-2 rounded-md p-1.5 hover:bg-accent/50">
                      <ActorAvatar actor={a.id} kind="capability" className="size-6" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm"><IdMono value={a.id} className="text-foreground" /></p>
                        <p className="text-xs text-muted-foreground">{formatRelative(a.at)}</p>
                      </div>
                      <StatusChip kind="instance" value={a.status} />
                    </Link>
                  </li>
                ))}
              </ol>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Open tasks quick list */}
      {openCount > 0 && (
        <Card className="mt-6">
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>Open decision gates</CardTitle>
            <Link to="/inbox" className="inline-flex items-center gap-1 text-sm text-agent hover:underline">
              Open inbox <ArrowRight className="size-3.5" />
            </Link>
          </CardHeader>
          <CardContent>
            <ul className="divide-y divide-border">
              {(openTasks ?? []).slice(0, 6).map((t) => (
                <li key={t.task_id}>
                  <Link to={`/inbox/${t.task_id}`} className="flex items-center gap-3 py-2 hover:bg-accent/30">
                    <ModeBadge mode={t.hitl_mode as HitlTaskMode} />
                    <span className="flex-1 text-sm">{t.title}</span>
                    <IdMono value={t.exception_id} />
                    <StatusChip kind="priority" value={t.priority} />
                  </Link>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </>
  );
}

function StatTile({
  to,
  tone,
  icon,
  label,
  value,
  hint,
  loading,
}: {
  to: string;
  tone: "attention" | "agent" | "success" | "danger";
  icon: React.ReactNode;
  label: string;
  value: number;
  hint?: string;
  loading?: boolean;
}) {
  const toneClass = {
    attention: "text-attention bg-attention-muted",
    agent: "text-agent bg-agent-muted",
    success: "text-success bg-success-muted",
    danger: "text-danger bg-danger-muted",
  }[tone];
  return (
    <Link to={to}>
      <Card className={cn("transition-colors hover:border-border/80", tone === "danger" && value > 0 && "border-danger/40")}>
        <CardContent className="flex items-center gap-3 p-4">
          <span className={cn("flex size-10 items-center justify-center rounded-lg", toneClass)}>{icon}</span>
          <div>
            {loading ? <Skeleton className="h-7 w-10" /> : <p className="text-2xl font-semibold tabular-nums">{value}</p>}
            <p className="text-xs text-muted-foreground">{label}</p>
          </div>
          {hint && <Badge variant="outline" className="ml-auto self-start text-[10px]">{hint}</Badge>}
        </CardContent>
      </Card>
    </Link>
  );
}
