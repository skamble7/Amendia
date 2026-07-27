import { request, requestText } from "../client";
import type { components } from "../gen/registry";
import type {
  ProcessPackManifest,
  CapabilityDescriptor,
  ArtifactSchemaRegistration,
  ResolveRequest,
  ResolveResponse,
} from "../types";

// ---- validation report / resolution (backend returns plain dicts; shapes captured
//      from the live registry — keep in sync with process-registry validation output) ----

export type FindingSeverity = "error" | "warning" | "info";

export interface ValidationFinding {
  code: string;
  severity: FindingSeverity;
  message: string;
  /** validator stage 1..7 — used to group the onboarding wizard report */
  stage: number;
  element_id: string | null;
  path: string | null;
}

export interface ValidationReport {
  pack_key: string;
  pack_version: string;
  findings: ValidationFinding[];
  created_at?: string;
}

export interface PackResolution {
  resolved_at: string;
  capabilities: Record<string, string>;
  artifacts: Record<string, string>;
  bindings: Record<string, unknown>;
  // ADR-027 Phase 2.5: the minimum execution profile this pack needs, derived from its BPMN at
  // activation and pinned here. Older packs (pre-2.5) omit it → treat as "common_subset".
  required_execution_profile?: string;
}

// ---- roles in use (derived from active packs' bindings + per-pack metadata sidecar) ----
// Mirrors app/models/registry.py::RoleInUse. This is the dynamic assignable-role source for
// the admin picker — role ids come from what active packs actually reference.

export interface RoleInUse {
  role_id: string;
  label?: string | null;
  description?: string | null;
  sources: string[]; // pack_key@version references
}

export function listRolesInUse(signal?: AbortSignal): Promise<RoleInUse[]> {
  return request<RoleInUse[]>("registry", "/roles", { signal });
}

// ---------------- Packs ----------------

export interface PackFilters {
  status?: string;
  limit?: number;
  offset?: number;
}

export function listPacks(filters: PackFilters = {}, signal?: AbortSignal): Promise<ProcessPackManifest[]> {
  return request<ProcessPackManifest[]>("registry", "/packs", { query: { ...filters }, signal });
}

export function getPackVersions(packKey: string, signal?: AbortSignal): Promise<ProcessPackManifest[]> {
  return request<ProcessPackManifest[]>("registry", `/packs/${packKey}`, { signal });
}

export function getPack(packKey: string, version: string, signal?: AbortSignal): Promise<ProcessPackManifest> {
  return request<ProcessPackManifest>("registry", `/packs/${packKey}/${version}`, { signal });
}

export function getPackBpmn(packKey: string, version: string, signal?: AbortSignal): Promise<string> {
  return requestText("registry", `/packs/${packKey}/${version}/bpmn`, { signal });
}

export function getValidationReport(packKey: string, version: string, signal?: AbortSignal): Promise<ValidationReport> {
  return request<ValidationReport>("registry", `/packs/${packKey}/${version}/validation-report`, { signal });
}

export function getPackResolution(packKey: string, version: string, signal?: AbortSignal): Promise<PackResolution> {
  return request<PackResolution>("registry", `/packs/${packKey}/${version}/resolution`, { signal });
}

// -- onboarding lifecycle (write side) --

export function createPack(manifest: ProcessPackManifest): Promise<ProcessPackManifest> {
  return request<ProcessPackManifest>("registry", "/packs", { method: "POST", body: manifest });
}

export function uploadBpmn(packKey: string, version: string, xml: string): Promise<{ pack_key: string; version: string; bpmn_sha256: string }> {
  return request("registry", `/packs/${packKey}/${version}/bpmn`, {
    method: "PUT",
    rawBody: { content: xml, contentType: "application/xml" },
  });
}

export function validatePack(packKey: string, version: string): Promise<ValidationReport> {
  return request<ValidationReport>("registry", `/packs/${packKey}/${version}/validate`, { method: "POST" });
}

export function activatePack(packKey: string, version: string): Promise<ProcessPackManifest> {
  return request<ProcessPackManifest>("registry", `/packs/${packKey}/${version}/activate`, { method: "POST" });
}

export function deprecatePack(packKey: string, version: string): Promise<ProcessPackManifest> {
  return request<ProcessPackManifest>("registry", `/packs/${packKey}/${version}/deprecate`, { method: "POST" });
}

// ---------------- Capabilities ----------------

export interface CapabilityFilters {
  status?: string;
  kind?: string;
  q?: string;              // free-text substring over capability_id + title (on-demand reuse search)
  limit?: number;
  offset?: number;
}

export function listCapabilities(filters: CapabilityFilters = {}, signal?: AbortSignal): Promise<CapabilityDescriptor[]> {
  return request<CapabilityDescriptor[]>("registry", "/capabilities", { query: { ...filters }, signal });
}

export function getCapabilityVersions(id: string, signal?: AbortSignal): Promise<CapabilityDescriptor[]> {
  return request<CapabilityDescriptor[]>("registry", `/capabilities/${id}`, { signal });
}

export function getCapability(id: string, version: string, signal?: AbortSignal): Promise<CapabilityDescriptor> {
  return request<CapabilityDescriptor>("registry", `/capabilities/${id}/${version}`, { signal });
}

// ---------------- Artifact schemas ----------------

export interface ArtifactSchemaFilters {
  status?: string;
  limit?: number;
  offset?: number;
}

export function listArtifactSchemas(filters: ArtifactSchemaFilters = {}, signal?: AbortSignal): Promise<ArtifactSchemaRegistration[]> {
  return request<ArtifactSchemaRegistration[]>("registry", "/artifact-schemas", { query: { ...filters }, signal });
}

export function getArtifactSchemaVersions(key: string, signal?: AbortSignal): Promise<ArtifactSchemaRegistration[]> {
  return request<ArtifactSchemaRegistration[]>("registry", `/artifact-schemas/${key}`, { signal });
}

export function getArtifactSchema(key: string, version: string, signal?: AbortSignal): Promise<ArtifactSchemaRegistration> {
  return request<ArtifactSchemaRegistration>("registry", `/artifact-schemas/${key}/${version}`, { signal });
}

// ---------------- Resolve ----------------

export function resolve(body: ResolveRequest): Promise<ResolveResponse> {
  return request<ResolveResponse>("registry", "/resolve", { method: "POST", body, silent: true });
}

// ---------------- Onboarding sessions (thin state-machine renderer) ----------------
// Types are GENERATED from the process-registry OpenAPI (webui/openapi/registry.json → gen/registry.ts;
// ADR-027 §5 / Phase 1.4) and aliased here so call sites keep their familiar names. openapi-typescript
// marks defaulted response fields optional; `Require<>` restores the collection fields the API always
// serializes so access stays ergonomic. `dry_run_report` is an untyped server-side dict (not a component),
// so it's re-typed to the hand-kept ValidationReport above. Drift is gated by `gen:api:check` (gen ↔
// snapshot) plus the process-registry `test_openapi_snapshot` (snapshot ↔ live app).

type _Schemas = components["schemas"];
type Require<T, K extends keyof T> = Omit<T, K> & { [P in K]-?: NonNullable<T[P]> };

export type OnboardingState = _Schemas["OnboardingState"];
export type OnbBasics = _Schemas["Basics"];
export type DocumentedElement = _Schemas["DocumentedElement"];
export type OnbLane = _Schemas["LaneSummary"];
export type OnbPool = _Schemas["PoolSummary"];
export type OnbMessageFlow = _Schemas["MessageFlowSummary"];
export type OnbEvent = _Schemas["EventSummary"];
export type OnbGatewayCondition = _Schemas["GatewayConditionSummary"];
export type OnbDataObject = _Schemas["DataObjectSummary"];
export type OnbBindableElement = _Schemas["BindableElementSummary"];
export type OnbBpmnInventory = Require<_Schemas["BpmnInventory"],
  "bindable_elements" | "service_tasks" | "user_tasks" | "gateways" | "task_names">;

export type InferredRole = _Schemas["InferredRole"];
export type InferredBinding = _Schemas["InferredBinding"];
export type InferredGatewayVariable = _Schemas["InferredGatewayVariable"];
export type CapabilityCandidate = _Schemas["CapabilityCandidate"];
export type ArtifactSeed = _Schemas["ArtifactSeed"];
export type SodCandidate = _Schemas["SodCandidate"];
export type InferenceAnnotation = _Schemas["InferenceAnnotation"];
export type InferenceDraft = Require<_Schemas["InferenceDraft"],
  "roles" | "bindings" | "gateway_variables" | "capability_candidates" | "artifact_seeds" | "sod_candidates" | "annotations">;

export type OnbStagedArtifact = _Schemas["StagedArtifact"];
export type OnbStagedCapability = _Schemas["StagedCapability"];
export type OnbBindingIO = _Schemas["StagedBindingIO"];
export type OnbStagedBinding = _Schemas["StagedBinding"];
export type OnbTriageRule = _Schemas["StagedTriageRule"];
export type OnbGatewayVariable = _Schemas["StagedGatewayVariable"];
export type OnbSod = _Schemas["StagedSod"];
export type OnbRoleMeta = _Schemas["RoleMeta"];
export type OnbCommitStep = _Schemas["CommitStep"];

type _Sess = Require<_Schemas["OnboardingSession"],
  "staged_artifacts" | "staged_capabilities" | "reused_capability_refs" | "bindings"
  | "triage_rules" | "gateway_variables" | "sod_policies" | "roles" | "commit_progress" | "last_cleared">;
// dry_run_report is an untyped dict server-side; bpmn/inferred need the collection-required aliases.
export type OnboardingSession = Omit<_Sess, "dry_run_report" | "bpmn" | "inferred"> & {
  dry_run_report?: ValidationReport | null;
  bpmn?: OnbBpmnInventory | null;
  inferred?: InferenceDraft | null;
};

export type ToolCompliance = Require<_Schemas["ToolCompliance"], "reasons">;
export type IntrospectedTool = _Schemas["IntrospectedTool"];
export type IntrospectMcpResponse = Require<_Schemas["IntrospectMcpResponse"], "tools">;
export type CapabilityToolSelection = _Schemas["CapabilityToolSelection"];
export type OnbDecisionSpec = _Schemas["DecisionSpec"];   // ADR-046 (Track 2)
export type OnbReduceSpec = _Schemas["ReduceSpec"];
export type BindingInput = _Schemas["BindingInput"];

// -- reads --
export function listOnboardingSessions(signal?: AbortSignal): Promise<OnboardingSession[]> {
  return request<OnboardingSession[]>("registry", "/onboarding", { signal });
}
export function getOnboardingSession(id: string, signal?: AbortSignal): Promise<OnboardingSession> {
  return request<OnboardingSession>("registry", `/onboarding/${id}`, { signal });
}

// -- transitions (silent: errors are rendered inline as field-level detail) --
export function createOnboardingSession(body: { pack_key: string; version: string; title: string; description?: string; default_domain: string }): Promise<OnboardingSession> {
  return request<OnboardingSession>("registry", "/onboarding", { method: "POST", body, silent: true });
}
export function deleteOnboardingSession(id: string): Promise<void> {
  return request<void>("registry", `/onboarding/${id}`, { method: "DELETE", silent: true });
}
export function attachOnboardingBpmn(id: string, body: { bpmn_xml: string; bpmn_file?: string }): Promise<OnboardingSession> {
  return request<OnboardingSession>("registry", `/onboarding/${id}/bpmn`, { method: "PUT", body, silent: true });
}
export function introspectMcp(body: { endpoint: string; transport?: string; headers?: Record<string, string>; domain: string }): Promise<IntrospectMcpResponse> {
  return request<IntrospectMcpResponse>("registry", "/capabilities/introspect-mcp", { method: "POST", body, silent: true });
}
export function setOnboardingCapabilities(id: string, body: {
  tools: CapabilityToolSelection[]; reused_capability_refs: string[];
  decision_specs?: OnbDecisionSpec[]; reduce_specs?: OnbReduceSpec[];   // ADR-046 (Track 2)
}): Promise<OnboardingSession> {
  return request<OnboardingSession>("registry", `/onboarding/${id}/capabilities`, { method: "POST", body, silent: true });
}
export function setOnboardingBindings(id: string, body: { bindings: BindingInput[] }): Promise<OnboardingSession> {
  return request<OnboardingSession>("registry", `/onboarding/${id}/bindings`, { method: "PUT", body, silent: true });
}
export function setOnboardingTriage(id: string, body: { triage_rules: OnbTriageRule[] }): Promise<OnboardingSession> {
  return request<OnboardingSession>("registry", `/onboarding/${id}/triage`, { method: "PUT", body, silent: true });
}
export function setOnboardingPolicies(id: string, body: { gateway_variables: OnbGatewayVariable[]; sod_policies: OnbSod[]; roles: string[]; role_meta?: Record<string, OnbRoleMeta> }): Promise<OnboardingSession> {
  return request<OnboardingSession>("registry", `/onboarding/${id}/policies`, { method: "PUT", body, silent: true });
}
export function assembleOnboarding(id: string): Promise<OnboardingSession> {
  return request<OnboardingSession>("registry", `/onboarding/${id}/assemble`, { method: "POST", silent: true });
}
export function commitOnboarding(id: string): Promise<OnboardingSession> {
  return request<OnboardingSession>("registry", `/onboarding/${id}/commit`, { method: "POST", silent: true });
}
