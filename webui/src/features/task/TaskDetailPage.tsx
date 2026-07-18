import { useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { ArrowLeft, Lock, UserCheck, Clock, TimerOff } from "lucide-react";
import { PageHeader } from "@/app/AppShell";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ModeBadge, StatusChip, IdMono, EmptyState } from "@/components/primitives";
import { ConnectivityState } from "@/components/ConnectivityState";
import { isConnectivityError } from "@/api/client";
import { HITL_MODE_META, type HitlTaskMode } from "@/lib/hitl";
import { taskEligibility } from "@/lib/tasks";
import { useCurrentIdentity } from "@/session/IdentityContext";
import { useHitlTask } from "./queries";
import { useTaskActions, type DecideArgs } from "./useTaskActions";
import { ContextRail } from "./ContextRail";
import { ProcessDiagramView } from "./ProcessDiagramView";
import { DecidedRecord } from "./DecidedRecord";
import type { ComponentType } from "react";
import { ReviewVariant, ApproveResultVariant, AuthorizeActionsVariant, ManualVariant, type VariantProps } from "./variants";

const VARIANT_COMPONENT: Record<HitlTaskMode, ComponentType<VariantProps>> = {
  review_after: ReviewVariant,
  approve_result: ApproveResultVariant,
  approve_actions: AuthorizeActionsVariant,
  manual: ManualVariant,
};

/** ADR-027 Phase 2.2: humanize the remaining time until an SLA timer boundary escalates this gate. */
function slaRemaining(dueAt: string): string {
  const ms = new Date(dueAt).getTime() - Date.now();
  if (ms <= 0) return "escalation imminent";
  const mins = Math.round(ms / 60000);
  if (mins < 60) return `in ${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `in ${h}h ${m}m` : `in ${h}h`;
}

/** SLA banner: a live gate with a timer boundary counts down to escalation; an expired gate shows
 * it breached and was escalated via the diagram's boundary path (ADR-027 Phase 2.2). */
function SlaBanner({ status, dueAt }: { status: string; dueAt?: string | null }) {
  if (status === "expired") {
    return (
      <Card className="border-danger/40 bg-danger-muted/20">
        <CardContent className="flex items-start gap-3 p-4">
          <TimerOff className="mt-0.5 size-5 text-danger" />
          <div>
            <p className="font-medium text-danger">SLA breached — escalated</p>
            <p className="text-sm text-muted-foreground">
              This gate’s deadline elapsed before a decision; the process routed to its escalation path.
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }
  if (!dueAt || (status !== "open" && status !== "claimed")) return null;
  return (
    <Card className="border-attention/40 bg-attention-muted/20">
      <CardContent className="flex items-center gap-3 p-4">
        <Clock className="size-5 text-attention" />
        <p className="text-sm">
          <span className="font-medium">SLA · escalates {slaRemaining(dueAt)}</span>{" "}
          <span className="text-muted-foreground">({new Date(dueAt).toLocaleString()})</span>
        </p>
      </CardContent>
    </Card>
  );
}

export function TaskDetailPage() {
  const { taskId } = useParams();
  const navigate = useNavigate();
  const identity = useCurrentIdentity();
  const { data: task, isLoading, error } = useHitlTask(taskId);
  const { claim, decide } = useTaskActions(taskId!);
  const [showDiagram, setShowDiagram] = useState(false);

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (isConnectivityError(error)) return <ConnectivityState error={error} />;

  if (!task) {
    return <EmptyState title="Task not found" description="It may have been cancelled or the id is invalid." action={<Button onClick={() => navigate("/inbox")}>Back to inbox</Button>} />;
  }

  // The BPMN process diagram opens in place (full width), replacing the task layout.
  if (showDiagram) {
    return <ProcessDiagramView task={task} onBack={() => setShowDiagram(false)} />;
  }

  const mode = task.hitl_mode as HitlTaskMode;
  const meta = HITL_MODE_META[mode];
  const elig = taskEligibility(task, identity.amendiaUserId, identity.roles);
  const Variant = VARIANT_COMPONENT[mode];
  const isDecided = task.status === "decided";
  const claimedByOther = task.status === "claimed" && task.assignee && task.assignee !== identity.amendiaUserId;
  const claimedByMe = task.status === "claimed" && task.assignee === identity.amendiaUserId;
  const pending = claim.isPending || decide.isPending;

  const onDecide = (args: DecideArgs) => decide.mutate(args);

  // Decisions require the claim to be held (the runtime enforces this); an open
  // task must be claimed first via the claim gate below.
  const canDecide = elig.canAct && claimedByMe;

  return (
    <>
      <div className="mb-4">
        <Link to="/inbox" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" /> Task inbox
        </Link>
      </div>
      <PageHeader
        title={task.title}
        description={meta?.meaning}
        badge={<ModeBadge mode={mode} />}
        actions={<StatusChip kind="task" value={task.status} />}
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4">
          {/* ADR-027 Phase 2.2: SLA countdown / escalation banner */}
          <SlaBanner status={task.status} dueAt={task.due_at} />

          {/* SoD / role lock banner */}
          {!elig.canAct && !isDecided && (
            <Card className="border-danger/40 bg-danger-muted/20">
              <CardContent className="flex items-start gap-3 p-4">
                <Lock className="mt-0.5 size-5 text-danger" />
                <div>
                  <p className="font-medium text-danger">You can’t act on this task</p>
                  <p className="text-sm text-muted-foreground">{elig.reason}</p>
                </div>
              </CardContent>
            </Card>
          )}

          {/* takeover banner */}
          {claimedByOther && !isDecided && (
            <Card className="border-attention/40 bg-attention-muted/20">
              <CardContent className="flex items-center justify-between gap-3 p-4">
                <div className="flex items-center gap-2">
                  <UserCheck className="size-5 text-attention" />
                  <p className="text-sm">
                    Claimed by <span className="font-medium">{task.assignee}</span>.
                  </p>
                </div>
                {elig.canAct && (
                  <Button size="sm" variant="outline" onClick={() => claim.mutate()} disabled={pending}>
                    Take over
                  </Button>
                )}
              </CardContent>
            </Card>
          )}

          {isDecided ? (
            <DecidedRecord task={task} />
          ) : (
            <Card>
              <CardContent className="p-5">
                {/* Claim gate: open + eligible → claim before deciding */}
                {task.status === "open" && elig.canAct ? (
                  <div className="mb-4 flex items-center justify-between rounded-md border border-border bg-surface/60 p-3">
                    <p className="text-sm text-muted-foreground">Claim this task to record a decision.</p>
                    <Button size="sm" onClick={() => claim.mutate()} disabled={pending}>
                      Claim task
                    </Button>
                  </div>
                ) : null}

                <fieldset disabled={!canDecide || pending} className={canDecide ? "" : "pointer-events-none opacity-60"}>
                  <Variant task={task} onDecide={onDecide} pending={pending} />
                </fieldset>
              </CardContent>
            </Card>
          )}

          <p className="text-center text-xs text-muted-foreground">
            <IdMono value={task.task_id} /> · gate <span className="font-mono">{task.element_id}</span>
          </p>
        </div>

        <ContextRail task={task} onOpenDiagram={() => setShowDiagram(true)} />
      </div>
    </>
  );
}
