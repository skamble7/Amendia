import { usePollingQuery } from "@/api/live";
import { listHitlTasks, type HitlTaskFilters } from "@/api/services/runtime";

/** Live inbox: poll HITL tasks with the given filters. */
export function useInboxTasks(filters: HitlTaskFilters) {
  return usePollingQuery({
    queryKey: ["hitl-tasks", filters],
    queryFn: (signal) => listHitlTasks(filters, signal),
  });
}
