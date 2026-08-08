import { useApiQuery } from "@/api/live";
import {
  listPacks,
  getPack,
  getPackVersions,
  getPackBpmn,
  getPackResolution,
  getValidationReport,
  listCapabilities,
  getCapability,
  listPackCapabilities,
  listPackArtifactSchemas,
  getArtifactSchemaVersions,
  listOnboardingSessions,
  getOnboardingSession,
  listRolesInUse,
  type PackFilters,
} from "@/api/services/registry";

export function usePacks(filters: PackFilters = {}) {
  return useApiQuery(["packs", filters], (s) => listPacks(filters, s));
}
export function usePackDetail(key: string | undefined, version: string | undefined) {
  return useApiQuery(["pack", key, version], (s) => getPack(key!, version!, s), { enabled: !!key && !!version, staleTime: Infinity });
}
export function usePackVersions(key: string | undefined) {
  return useApiQuery(["pack-versions", key], (s) => getPackVersions(key!, s), { enabled: !!key });
}
export function usePackBpmn(key: string | undefined, version: string | undefined) {
  return useApiQuery(["pack-bpmn", key, version], (s) => getPackBpmn(key!, version!, s), { enabled: !!key && !!version, staleTime: Infinity });
}
export function usePackResolution(key: string | undefined, version: string | undefined) {
  return useApiQuery(["pack-resolution", key, version], (s) => getPackResolution(key!, version!, s), { enabled: !!key && !!version });
}
export function useValidationReport(key: string | undefined, version: string | undefined) {
  return useApiQuery(["validation-report", key, version], (s) => getValidationReport(key!, version!, s), { enabled: !!key && !!version });
}
// The onboarding wizard's cross-pack reuse browse (all owned rows). NOT a pack-scoped view — see
// usePackCapabilities/usePackSchemas below for a pack version's OWNED catalog (ADR-060).
export function useCapabilities() {
  return useApiQuery(["capabilities"], (s) => listCapabilities({}, s));
}
// On-demand reuse search (does NOT eager-load the catalog): only queries once a term is entered.
export function useCapabilitySearch(term: string) {
  const q = term.trim();
  return useApiQuery(["capability-search", q], (s) => listCapabilities({ q, status: "active", limit: 20 }, s), { enabled: q.length > 0 });
}
// ADR-060/061: a pack VERSION's OWNED capabilities / schemas (the pack detail view). ADR-061 Phase 4
// repointed these to the NESTED collection routes (/packs/{pk}/{pv}/capabilities|artifact-schemas) —
// no shared catalog, no query-param browse.
export function usePackCapabilities(packKey: string | undefined, packVersion: string | undefined) {
  return useApiQuery(
    ["pack-capabilities", packKey, packVersion],
    (s) => listPackCapabilities(packKey!, packVersion!, s),
    { enabled: !!packKey && !!packVersion },
  );
}
export function usePackSchemas(packKey: string | undefined, packVersion: string | undefined) {
  return useApiQuery(
    ["pack-schemas", packKey, packVersion],
    (s) => listPackArtifactSchemas(packKey!, packVersion!, s),
    { enabled: !!packKey && !!packVersion },
  );
}
// ADR-060: capability/schema single + versions reads are pack-scoped — pass the owning pack's coords.
export function useCapability(packKey: string | undefined, packVersion: string | undefined, id: string | undefined, version: string | undefined) {
  return useApiQuery(
    ["capability", packKey, packVersion, id, version],
    (s) => getCapability(packKey!, packVersion!, id!, version!, s),
    { enabled: !!packKey && !!packVersion && !!id && !!version },
  );
}
export function useArtifactSchemaVersions(packKey: string | undefined, packVersion: string | undefined, key: string | undefined) {
  return useApiQuery(
    ["artifact-schema-versions", packKey, packVersion, key],
    (s) => getArtifactSchemaVersions(packKey!, packVersion!, key!, s),
    { enabled: !!packKey && !!packVersion && !!key },
  );
}
export function useOnboardingSessions() {
  return useApiQuery(["onboarding-sessions"], (s) => listOnboardingSessions(s));
}
export function useOnboardingSession(id: string | undefined) {
  return useApiQuery(["onboarding-session", id], (s) => getOnboardingSession(id!, s), { enabled: !!id, staleTime: Infinity });
}
/** Assignable-role catalog: role ids derived from active packs' bindings + authored metadata. */
export function useRolesInUse() {
  return useApiQuery(["roles-in-use"], (s) => listRolesInUse(s));
}
