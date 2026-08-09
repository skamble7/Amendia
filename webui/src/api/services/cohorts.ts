import { request } from "../client";
import { listPacks } from "./registry";
import type {
  CohortDefinition,
  CohortDetailOut,
  CohortListOut,
  CohortState,
  ProcessPackManifest,
} from "../types";

/**
 * ADR-063 Phase 3B cohort calls. Reads are served by glea-service (event-sourced, observability-grade) and
 * are OPTIONAL at the UI layer — a connectivity failure (0), missing service (404), or unavailable store (503)
 * degrades to `null` (empty/unavailable state, never a crash), mirroring the other glea reads. Definition +
 * membership writes go to the registry.
 */
async function optional<T>(fn: () => Promise<T>): Promise<T | null> {
  try {
    return await fn();
  } catch (err) {
    const status = (err as { status?: number }).status;
    if (status === 0 || status === 404 || status === 503) return null;
    throw err;
  }
}

// ---- glea: cohort read-models ----
export function getCohorts(state?: CohortState, signal?: AbortSignal): Promise<CohortListOut | null> {
  return optional(() =>
    request<CohortListOut>("glea", "/cohorts", { query: { state }, signal, silent: true }),
  );
}

export function getCohort(id: string, signal?: AbortSignal): Promise<CohortDetailOut | null> {
  return optional(() => request<CohortDetailOut>("glea", `/cohorts/${id}`, { signal, silent: true }));
}

export function getCohortByCorrelation(value: string, signal?: AbortSignal): Promise<CohortDetailOut | null> {
  return optional(() =>
    request<CohortDetailOut>("glea", `/cohorts/by-correlation/${value}`, { signal, silent: true }),
  );
}

// ---- registry: cohort definitions + membership ----
export function listCohortDefinitions(signal?: AbortSignal): Promise<CohortDefinition[]> {
  return request<CohortDefinition[]>("registry", "/cohort/definitions", { signal });
}

export function createCohortDefinition(body: CohortDefinition): Promise<CohortDefinition> {
  return request<CohortDefinition>("registry", "/cohort/definitions", { method: "POST", body, silent: true });
}

/** Owner-gated (server-side) delete of a cohort definition. The backend DELETE is idempotent (204). */
export function deleteCohortDefinition(cohortDefId: string): Promise<void> {
  return request<void>("registry", `/cohort/definitions/${cohortDefId}`, { method: "DELETE", silent: true });
}

/** Owner-gated inline update of a definition's MUTABLE fields (cohort_def_id is immutable — path-only). */
export type CohortDefinitionUpdate = {
  display_name: string | null;
  description: string | null;
  close_schema: Record<string, unknown>;
  close_correlation_path: string;
  close_outcome_path: string | null;
};
export function updateCohortDefinition(cohortDefId: string, body: CohortDefinitionUpdate): Promise<CohortDefinition> {
  return request<CohortDefinition>("registry", `/cohort/definitions/${cohortDefId}`, { method: "PUT", body, silent: true });
}

export function assignMembership(
  packKey: string,
  version: string,
  body: { cohort_def_id: string; correlation_key: string },
): Promise<ProcessPackManifest> {
  return request<ProcessPackManifest>("registry", `/packs/${packKey}/${version}/cohort-membership`, {
    method: "PUT",
    body,
    silent: true,
  });
}

export function clearMembership(packKey: string, version: string): Promise<ProcessPackManifest> {
  return request<ProcessPackManifest>("registry", `/packs/${packKey}/${version}/cohort-membership`, {
    method: "DELETE",
    silent: true,
  });
}

export function getTriggerFields(packKey: string, version: string, signal?: AbortSignal): Promise<string[]> {
  return request<{ fields: string[] }>("registry", `/packs/${packKey}/${version}/trigger-fields`, { signal })
    .then((r) => r.fields ?? []);
}

/** Active onboarded packs (the membership picker's source). */
export function listActivePacks(signal?: AbortSignal): Promise<ProcessPackManifest[]> {
  return listPacks({ status: "active" }, signal);
}
