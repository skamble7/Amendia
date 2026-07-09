import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { claimTask, decideTask } from "@/api/services/runtime";
import { ApiError } from "@/api/client";
import type { Decision } from "@/lib/hitl";

export interface DecideArgs {
  decision: Decision;
  comment?: string;
  edits?: Record<string, unknown>;
  approved_action_ids?: string[];
}

/**
 * Claim + decide plumbing for a task, with the design's error semantics:
 *  - 403 → SoD / role toast + surfaced so the page can show the lock banner
 *  - 409 → already-claimed / already-decided toast + refetch (takeover banner)
 *  - 400 → edit re-validation failure; surface the backend detail
 * On success the task + related instance queries are invalidated so the UI
 * reflects the advanced state immediately.
 *
 * Identity is never sent in a body — the runtime derives the actor from the
 * bearer token. claim carries no body; decide carries only the decision.
 */
export function useTaskActions(taskId: string) {
  const qc = useQueryClient();

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["hitl-task", taskId] });
    qc.invalidateQueries({ queryKey: ["hitl-tasks"] });
    qc.invalidateQueries({ queryKey: ["instances"] });
    qc.invalidateQueries({ queryKey: ["instance"] });
  };

  const claim = useMutation({
    mutationFn: () => claimTask(taskId),
    onSuccess: () => {
      toast.success("Task claimed");
      invalidate();
    },
    onError: (err: ApiError) => handleError(err, invalidate),
  });

  const decide = useMutation({
    mutationFn: async (args: DecideArgs) => {
      return decideTask(taskId, {
        decision: args.decision,
        comment: args.comment,
        edits: args.edits,
        approved_action_ids: args.approved_action_ids,
      });
    },
    onSuccess: (_data, args) => {
      toast.success(`Decision recorded: ${args.decision.replace(/_/g, " ")}`);
      invalidate();
    },
    onError: (err: ApiError) => handleError(err, invalidate),
  });

  return { claim, decide };
}

function handleError(err: ApiError, invalidate: () => void) {
  if (err.status === 403) {
    toast.error(err.detailText || "Separation of duties: you cannot act on this task.");
  } else if (err.status === 409) {
    toast.error(err.detailText || "This task was already claimed or decided.");
    invalidate();
  } else if (err.status === 400 || err.status === 422) {
    toast.error(`Validation failed: ${err.detailText}`);
  } else {
    toast.error(err.detailText || "Something went wrong.");
  }
}
