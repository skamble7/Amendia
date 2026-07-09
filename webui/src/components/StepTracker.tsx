import { Check, X, Bot, User, Circle } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { Step } from "@/lib/steps";

const STATE_STYLE: Record<Step["state"], string> = {
  done: "bg-success/15 text-success border-success/30",
  current: "bg-agent/15 text-agent border-agent/40 ring-2 ring-agent/30",
  pending: "bg-muted text-muted-foreground border-border",
  failed: "bg-danger/15 text-danger border-danger/40",
};

function StepDot({ step }: { step: Step }) {
  const icon =
    step.state === "done" ? <Check className="size-3.5" /> : step.state === "failed" ? <X className="size-3.5" /> : step.kind === "userTask" ? <User className="size-3.5" /> : <Bot className="size-3.5" />;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="flex flex-col items-center gap-1">
          <span className={cn("flex size-7 items-center justify-center rounded-full border", STATE_STYLE[step.state])}>
            {step.state === "pending" ? <Circle className="size-2 fill-current" /> : icon}
          </span>
        </div>
      </TooltipTrigger>
      <TooltipContent>
        <p className="font-medium">{step.label}</p>
        <p className="text-muted-foreground">
          {step.kind === "userTask" ? "Human" : "Agent"}
          {step.hitl_mode && step.hitl_mode !== "none" ? ` · ${step.hitl_mode.replace(/_/g, " ")}` : ""} · {step.state}
        </p>
      </TooltipContent>
    </Tooltip>
  );
}

/** Horizontal (compact) or vertical step tracker. */
export function StepTracker({ steps, compact = false, className }: { steps: Step[]; compact?: boolean; className?: string }) {
  if (steps.length === 0) return null;

  if (compact) {
    return (
      <div className={cn("flex items-center gap-1 overflow-x-auto", className)}>
        {steps.map((s, i) => (
          <div key={s.element_id} className="flex items-center">
            <StepDot step={s} />
            {i < steps.length - 1 && <span className={cn("h-px w-3", s.state === "done" ? "bg-success/40" : "bg-border")} />}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className={cn("space-y-1", className)}>
      {steps.map((s, i) => (
        <div key={s.element_id} className="flex items-center gap-3">
          <div className="flex flex-col items-center">
            <StepDot step={s} />
            {i < steps.length - 1 && <span className={cn("h-5 w-px", s.state === "done" ? "bg-success/40" : "bg-border")} />}
          </div>
          <div className="pb-4">
            <p className={cn("text-sm", s.state === "current" ? "font-medium text-agent" : s.state === "failed" ? "text-danger" : "")}>
              {s.label}
            </p>
            <p className="text-xs text-muted-foreground">
              {s.kind === "userTask" ? "Human" : "Agent"}
              {s.hitl_mode && s.hitl_mode !== "none" ? ` · ${s.hitl_mode.replace(/_/g, " ")}` : ""}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}
