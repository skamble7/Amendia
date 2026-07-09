import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Lock, Inbox as InboxIcon } from "lucide-react";
import { PageHeader } from "@/app/AppShell";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusChip, ModeBadge, IdMono, LiveDot, EmptyState } from "@/components/primitives";
import { Badge } from "@/components/ui/badge";
import { ConnectivityState } from "@/components/ConnectivityState";
import { isConnectivityError } from "@/api/client";
import { GenerateExceptionButton } from "@/features/exceptions/GenerateExceptionButton";
import { useCurrentIdentity } from "@/session/IdentityContext";
import { useInboxTasks } from "./queries";
import { taskEligibility, roleLabel } from "@/lib/tasks";
import { formatCountdown } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { HitlTask } from "@/api/types";
import type { HitlTaskMode } from "@/lib/hitl";

const MODE_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "All modes" },
  { value: "review_after", label: "Review" },
  { value: "approve_result", label: "Approve result" },
  { value: "approve_actions", label: "Authorize actions" },
  { value: "manual", label: "Manual" },
];
const STATUS_OPTIONS = ["open", "claimed", "decided", ""].map((v) => ({ value: v, label: v ? v[0]!.toUpperCase() + v.slice(1) : "All statuses" }));
const ROLE_OPTIONS = [
  { value: "", label: "All roles" },
  { value: "role.payments.ops_analyst", label: "Analyst" },
  { value: "role.payments.ops_approver", label: "Approver" },
];
const PRIORITY_OPTIONS = [
  { value: "", label: "All priorities" },
  { value: "critical", label: "Critical" },
  { value: "high", label: "High" },
  { value: "normal", label: "Normal" },
  { value: "low", label: "Low" },
];

function Select({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: { value: string; label: string }[] }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-8 rounded-md border border-input bg-transparent px-2 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function InboxPage() {
  const identity = useCurrentIdentity();
  const navigate = useNavigate();
  const [status, setStatus] = useState("open");
  const [mode, setMode] = useState("");
  const [role, setRole] = useState("");
  const [priority, setPriority] = useState("");

  const { data: tasks, isLoading, isFetching, error } = useInboxTasks({ status: status || undefined, role: role || undefined });

  const filtered = useMemo(() => {
    let rows = tasks ?? [];
    if (mode) rows = rows.filter((t) => t.hitl_mode === mode);
    if (priority) rows = rows.filter((t) => t.priority === priority);
    // most urgent first: priority then due date
    const order = { critical: 0, high: 1, normal: 2, low: 3 } as Record<string, number>;
    return [...rows].sort((a, b) => (order[a.priority ?? "normal"]! - order[b.priority ?? "normal"]!) || (a.due_at ?? "").localeCompare(b.due_at ?? ""));
  }, [tasks, mode, priority]);

  // amber-flash rows whose updated_at changed since last poll
  const seen = useRef<Map<string, string>>(new Map());
  const [flash, setFlash] = useState<Set<string>>(new Set());
  useEffect(() => {
    const changed = new Set<string>();
    for (const t of filtered) {
      const prev = seen.current.get(t.task_id);
      if (prev !== undefined && prev !== t.updated_at) changed.add(t.task_id);
      seen.current.set(t.task_id, t.updated_at ?? "");
    }
    if (changed.size) {
      setFlash(changed);
      const id = setTimeout(() => setFlash(new Set()), 1600);
      return () => clearTimeout(id);
    }
  }, [filtered]);

  return (
    <>
      <PageHeader
        title="Task inbox"
        description="Human decision gates across all running instances."
        badge={isFetching ? <LiveDot label="Live" /> : undefined}
      />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Select value={status} onChange={setStatus} options={STATUS_OPTIONS} />
        <Select value={mode} onChange={setMode} options={MODE_OPTIONS} />
        <Select value={role} onChange={setRole} options={ROLE_OPTIONS} />
        <Select value={priority} onChange={setPriority} options={PRIORITY_OPTIONS} />
        <span className="ml-auto text-xs text-muted-foreground">{filtered.length} task{filtered.length === 1 ? "" : "s"}</span>
      </div>

      {isConnectivityError(error) ? (
        <ConnectivityState error={error} />
      ) : (
      <div className="rounded-lg border border-border bg-surface">
        {isLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          status === "open" && !mode && !role && !priority ? (
            <EmptyState
              icon={<InboxIcon className="size-6" />}
              title="No open tasks yet"
              description="Generate an exception from the stub source and work its gates here."
              action={<GenerateExceptionButton />}
            />
          ) : (
            <EmptyState icon={<InboxIcon className="size-6" />} title="No tasks match" description="Adjust the filters, or wait for new gates to open." />
          )
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Exception</TableHead>
                <TableHead>Gate</TableHead>
                <TableHead>Mode</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Priority</TableHead>
                <TableHead>Assignee</TableHead>
                <TableHead>SLA</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((t) => (
                <InboxRow
                  key={t.task_id}
                  task={t}
                  flash={flash.has(t.task_id)}
                  amendiaUserId={identity.amendiaUserId}
                  roles={identity.roles}
                  onOpen={() => navigate(`/inbox/${t.task_id}`)}
                />
              ))}
            </TableBody>
          </Table>
        )}
      </div>
      )}
    </>
  );
}

function InboxRow({
  task,
  flash,
  amendiaUserId,
  roles,
  onOpen,
}: {
  task: HitlTask;
  flash: boolean;
  amendiaUserId: string;
  roles: string[];
  onOpen: () => void;
}) {
  const elig = taskEligibility(task, amendiaUserId, roles);
  const countdown = formatCountdown(task.due_at);

  return (
    <TableRow
      className={cn("cursor-pointer", flash && "animate-amber-flash", elig.sodLocked && "bg-danger-muted/20")}
      onClick={onOpen}
      tabIndex={0}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onOpen())}
      aria-label={`Task ${task.title} for ${task.exception_id}`}
    >
      <TableCell>
        <IdMono value={task.exception_id} />
      </TableCell>
      <TableCell>
        <div className="flex items-center gap-2">
          {!elig.canAct && (
            <Tooltip>
              <TooltipTrigger asChild>
                <span aria-label={elig.reason ?? "locked"} className={cn(elig.sodLocked ? "text-danger" : "text-muted-foreground")}>
                  <Lock className="size-3.5" />
                </span>
              </TooltipTrigger>
              <TooltipContent>{elig.reason}</TooltipContent>
            </Tooltip>
          )}
          <span className="font-medium">{task.title}</span>
        </div>
      </TableCell>
      <TableCell>
        <ModeBadge mode={task.hitl_mode as HitlTaskMode} />
      </TableCell>
      <TableCell className="text-sm text-muted-foreground">{roleLabel(task.role)}</TableCell>
      <TableCell>
        <StatusChip kind="priority" value={task.priority} />
      </TableCell>
      <TableCell>
        {task.assignee ? (
          <div className="flex items-center gap-1.5">
            <Avatar className="size-6">
              <AvatarFallback className="bg-muted text-[10px]">{task.assignee.slice(0, 2).toUpperCase()}</AvatarFallback>
            </Avatar>
            <span className="text-xs text-muted-foreground">{task.assignee}</span>
          </div>
        ) : (
          <span className="text-xs text-muted-foreground">Unassigned</span>
        )}
      </TableCell>
      <TableCell>
        <Badge variant={countdown.overdue ? "danger" : "outline"} className="tabular-nums">
          {countdown.text}
        </Badge>
      </TableCell>
      <TableCell>
        <StatusChip kind="task" value={task.status} />
      </TableCell>
    </TableRow>
  );
}
