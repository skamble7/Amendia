import { useApiQuery } from "@/api/live";
import {
  listPacks,
  getPack,
  getPackBpmn,
  getPackResolution,
  getValidationReport,
  listCapabilities,
  getCapability,
  listArtifactSchemas,
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
export function usePackBpmn(key: string | undefined, version: string | undefined) {
  return useApiQuery(["pack-bpmn", key, version], (s) => getPackBpmn(key!, version!, s), { enabled: !!key && !!version, staleTime: Infinity });
}
export function usePackResolution(key: string | undefined, version: string | undefined) {
  return useApiQuery(["pack-resolution", key, version], (s) => getPackResolution(key!, version!, s), { enabled: !!key && !!version });
}
export function useValidationReport(key: string | undefined, version: string | undefined) {
  return useApiQuery(["validation-report", key, version], (s) => getValidationReport(key!, version!, s), { enabled: !!key && !!version });
}
export function useCapabilities() {
  return useApiQuery(["capabilities"], (s) => listCapabilities({}, s));
}
export function useCapability(id: string | undefined, version: string | undefined) {
  return useApiQuery(["capability", id, version], (s) => getCapability(id!, version!, s), { enabled: !!id && !!version });
}
export function useArtifactSchemas() {
  return useApiQuery(["artifact-schemas-list"], (s) => listArtifactSchemas({}, s));
}
export function useArtifactSchemaVersions(key: string | undefined) {
  return useApiQuery(["artifact-schema-versions", key], (s) => getArtifactSchemaVersions(key!, s), { enabled: !!key });
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
