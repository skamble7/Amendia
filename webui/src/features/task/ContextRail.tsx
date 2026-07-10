import { Link } from "react-router-dom";
import { Clock, ExternalLink, Maximize } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { StepTracker } from "@/components/StepTracker";
import { ExceptionSummary } from "@/features/exceptions/ExceptionSummary";
import { useApiQuery } from "@/api/live";
import { getException } from "@/api/services/stub";
import { useProcessProgress } from "./useProcessProgress";
import { formatCountdown } from "@/lib/format";
import type { HitlTask } from "@/api/types";

export function ContextRail({ task, onOpenDiagram }: { task: HitlTask; onOpenDiagram?: () => void }) {
  const { data: exc } = useApiQuery(["exception", task.exception_id], (s) => getException(task.exception_id, s));
  const { pack, steps } = useProcessProgress(task);
  const countdown = formatCountdown(task.due_at);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Exception</CardTitle>
          <Link to={`/exceptions/${task.exception_id}`} className="text-muted-foreground hover:text-foreground" aria-label="Open exception">
            <ExternalLink className="size-4" />
          </Link>
        </CardHeader>
        <CardContent>
          <ExceptionSummary exc={exc} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Process progress</CardTitle>
          <div className="flex items-center gap-2">
            <Link to={`/instances/${task.process_instance_id}`} className="text-xs text-muted-foreground hover:text-foreground">
              {task.process_instance_id}
            </Link>
            <button
              type="button"
              onClick={onOpenDiagram}
              disabled={!pack || !onOpenDiagram}
              aria-label="Open BPMN process diagram"
              title="Open BPMN process diagram"
              className="text-muted-foreground transition-colors hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Maximize className="size-4" />
            </button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="max-h-72 overflow-y-auto pr-1">
            <StepTracker steps={steps} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Clock className="size-4" /> SLA
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Badge variant={countdown.overdue ? "danger" : "attention"} className="tabular-nums">
            {countdown.text}
          </Badge>
        </CardContent>
      </Card>
    </div>
  );
}
