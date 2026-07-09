import { Link } from "react-router-dom";
import { Clock, ExternalLink } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { StepTracker } from "@/components/StepTracker";
import { ExceptionSummary } from "@/features/exceptions/ExceptionSummary";
import { useApiQuery } from "@/api/live";
import { getException } from "@/api/services/stub";
import { getPack } from "@/api/services/registry";
import { getInstance } from "@/api/services/runtime";
import { deriveSteps } from "@/lib/steps";
import { formatCountdown } from "@/lib/format";
import type { HitlTask } from "@/api/types";

export function ContextRail({ task }: { task: HitlTask }) {
  const { data: exc } = useApiQuery(["exception", task.exception_id], (s) => getException(task.exception_id, s));
  const { data: pack } = useApiQuery(["pack", task.pack_key, task.pack_version], (s) => getPack(task.pack_key, task.pack_version, s), {
    staleTime: Infinity,
  });
  const { data: instance } = useApiQuery(["instance", task.process_instance_id], (s) => getInstance(task.process_instance_id, s));

  const steps = deriveSteps(pack, instance?.actor_log, { currentElementId: task.element_id });
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
          <CardTitle>Progress</CardTitle>
          <Link to={`/instances/${task.process_instance_id}`} className="text-xs text-muted-foreground hover:text-foreground">
            {task.process_instance_id}
          </Link>
        </CardHeader>
        <CardContent>
          <StepTracker steps={steps} compact className="mb-1" />
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
