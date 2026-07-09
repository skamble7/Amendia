import { usePollingQuery } from "@/api/live";
import { getHitlTask } from "@/api/services/runtime";

/** Poll a single task so takeovers / decisions by others surface promptly. */
export function useHitlTask(taskId: string | undefined) {
  return usePollingQuery({
    queryKey: ["hitl-task", taskId],
    queryFn: (signal) => getHitlTask(taskId!, signal),
    enabled: !!taskId,
    intervalMs: 5000,
  });
}
