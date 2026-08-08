import { useApiQuery, usePollingQuery } from "@/api/live";
import {
  getCohort,
  getCohortByCorrelation,
  getCohorts,
  listActivePacks,
  listCohortDefinitions,
  getTriggerFields,
} from "@/api/services/cohorts";
import type { CohortState } from "@/api/types";

export function useCohorts(state?: CohortState) {
  return usePollingQuery({
    queryKey: ["cohorts", state ?? "all"],
    queryFn: (s) => getCohorts(state, s),
  });
}

export function useCohort(id: string | undefined) {
  return usePollingQuery({
    queryKey: ["cohort", id],
    queryFn: (s) => getCohort(id!, s),
    enabled: !!id,
    intervalMs: 5000,
  });
}

export function useCohortByCorrelation(value: string | undefined) {
  return usePollingQuery({
    queryKey: ["cohort-by-correlation", value],
    queryFn: (s) => getCohortByCorrelation(value!, s),
    enabled: !!value,
    intervalMs: 5000,
  });
}

export function useCohortDefinitions() {
  return useApiQuery(["cohort-definitions"], (s) => listCohortDefinitions(s));
}

export function useActivePacks() {
  return useApiQuery(["active-packs"], (s) => listActivePacks(s));
}

export function useTriggerFields(packKey: string | undefined, version: string | undefined) {
  return useApiQuery(
    ["trigger-fields", packKey, version],
    (s) => getTriggerFields(packKey!, version!, s),
    { enabled: !!packKey && !!version, staleTime: Infinity },
  );
}
