import { Bot, User, ShieldAlert, Shield } from "lucide-react";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { formatMoney } from "@/lib/format";
import { statusMeta, INSTANCE_STATUS, INGESTION_STATUS, TASK_STATUS, TASK_PRIORITY } from "@/lib/status";
import { HITL_MODE_META, type HitlTaskMode } from "@/lib/hitl";

type StatusKind = "instance" | "ingestion" | "task" | "priority";

const STATUS_MAPS = {
  instance: INSTANCE_STATUS,
  ingestion: INGESTION_STATUS,
  task: TASK_STATUS,
  priority: TASK_PRIORITY,
};

/** Status pill for instance / ingestion / task / priority enums. */
export function StatusChip({
  kind,
  value,
  className,
}: {
  kind: StatusKind;
  value: string | null | undefined;
  className?: string;
}) {
  const meta = statusMeta(STATUS_MAPS[kind], value);
  return (
    <Badge variant={meta.variant} className={className} aria-label={`${kind} status: ${meta.label}`}>
      {meta.label}
    </Badge>
  );
}

const MODE_VARIANT: Record<HitlTaskMode, BadgeProps["variant"]> = {
  review_after: "agent",
  approve_result: "artifact",
  approve_actions: "process",
  manual: "attention",
};

/** HITL mode badge with the design's semantic color per mode. */
export function ModeBadge({ mode, className }: { mode: HitlTaskMode; className?: string }) {
  const meta = HITL_MODE_META[mode];
  if (!meta) return <Badge variant="outline" className={className}>{mode}</Badge>;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge variant={MODE_VARIANT[mode]} className={className}>
          {meta.label}
        </Badge>
      </TooltipTrigger>
      <TooltipContent>{meta.meaning}</TooltipContent>
    </Tooltip>
  );
}

/** Monospaced id with tabular figures; optional copy-friendly full title. */
export function IdMono({ value, className }: { value: string | null | undefined; className?: string }) {
  return (
    <span className={cn("font-mono text-xs tabular-nums text-muted-foreground", className)} title={value ?? undefined}>
      {value ?? "—"}
    </span>
  );
}

/** Amount with tabular figures; emphasises currency + value. */
export function AmountDisplay({
  amount,
  currency,
  className,
}: {
  amount: number | string | null | undefined;
  currency?: string | null;
  className?: string;
}) {
  return (
    <span className={cn("font-medium tabular-nums", className)}>{formatMoney(amount, currency)}</span>
  );
}

/** ISO 20022 reason code (AC01, BE04, …). */
export function ReasonCodeBadge({ code, className }: { code: string; className?: string }) {
  return (
    <Badge variant="outline" className={cn("font-mono", className)}>
      {code}
    </Badge>
  );
}

/** Side-effect flag for capabilities/bindings. */
export function SideEffectBadge({ sideEffect }: { sideEffect: "read_only" | "side_effectful" | string }) {
  if (sideEffect === "side_effectful") {
    return (
      <Badge variant="process">
        <ShieldAlert className="size-3" /> Side-effectful
      </Badge>
    );
  }
  return (
    <Badge variant="outline">
      <Shield className="size-3" /> Read-only
    </Badge>
  );
}

/** Actor avatar: purple bot for capability/agent, neutral for human. */
export function ActorAvatar({
  actor,
  kind,
  className,
}: {
  actor: string;
  kind: "capability" | "human" | string;
  className?: string;
}) {
  const isAgent = kind === "capability";
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Avatar className={cn("size-7", className)}>
          <AvatarFallback className={isAgent ? "bg-agent-muted text-agent" : "bg-muted text-foreground"}>
            {isAgent ? <Bot className="size-4" /> : <User className="size-4" />}
          </AvatarFallback>
        </Avatar>
      </TooltipTrigger>
      <TooltipContent>
        {isAgent ? "Agent" : "Human"}: {actor}
      </TooltipContent>
    </Tooltip>
  );
}

/** Small pulsing dot indicating a live/polling surface. */
export function LiveDot({ className, label = "Live" }: { className?: string; label?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs text-muted-foreground", className)}>
      <span className="relative flex size-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-60" />
        <span className="relative inline-flex size-2 rounded-full bg-success" />
      </span>
      {label}
    </span>
  );
}

/** Empty-state placeholder used wherever a query returns nothing. */
export function EmptyState({
  title,
  description,
  icon,
  action,
}: {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border bg-surface/40 px-6 py-16 text-center">
      {icon && <div className="text-muted-foreground">{icon}</div>}
      <div className="space-y-1">
        <p className="text-sm font-medium">{title}</p>
        {description && <p className="max-w-sm text-sm text-muted-foreground">{description}</p>}
      </div>
      {action}
    </div>
  );
}
