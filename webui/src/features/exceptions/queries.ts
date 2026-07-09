import { usePollingQuery, useApiQuery } from "@/api/live";
import { listIngestions, getIngestion, type IngestionFilters } from "@/api/services/ingestor";
import { getException } from "@/api/services/stub";

export function useIngestions(filters: IngestionFilters = {}) {
  return usePollingQuery({
    queryKey: ["ingestions", filters],
    queryFn: (signal) => listIngestions(filters, signal),
  });
}

export function useIngestion(exceptionId: string | undefined) {
  return usePollingQuery({
    queryKey: ["ingestion", exceptionId],
    queryFn: (signal) => getIngestion(exceptionId!, signal),
    enabled: !!exceptionId,
    intervalMs: 5000,
  });
}

export function useException(exceptionId: string | undefined) {
  return useApiQuery(["exception", exceptionId], (signal) => getException(exceptionId!, signal), { enabled: !!exceptionId });
}
