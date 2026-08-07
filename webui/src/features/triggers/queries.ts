import { usePollingQuery, useApiQuery } from "@/api/live";
import { listIngestions, getIngestion, type IngestionFilters } from "@/api/services/ingestor";
import { getTrigger } from "@/api/services/stub";

export function useIngestions(filters: IngestionFilters = {}) {
  return usePollingQuery({
    queryKey: ["ingestions", filters],
    queryFn: (signal) => listIngestions(filters, signal),
  });
}

export function useIngestion(triggerId: string | undefined) {
  return usePollingQuery({
    queryKey: ["ingestion", triggerId],
    queryFn: (signal) => getIngestion(triggerId!, signal),
    enabled: !!triggerId,
    intervalMs: 5000,
  });
}

export function useTrigger(triggerId: string | undefined) {
  return useApiQuery(["trigger", triggerId], (signal) => getTrigger(triggerId!, signal), { enabled: !!triggerId });
}
