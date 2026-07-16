import { request, requestText } from "../client";
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
// The backend OnboardingSession is a registry-owned authoring scratch doc; the webui only
// renders it. Shapes mirror app/models/onboarding.py — kept in sync by hand (like the
// ValidationReport types above), not hand-authored elsewhere.

export type OnboardingState =
  | "initiated" | "bpmn_attached" | "capabilities_resolved" | "bindings_set"
  | "triage_set" | "policies_set" | "assembled" | "completed";

export interface OnbBasics { pack_key: string; version: string; title: string; description?: string | null; default_domain: string; }
export interface OnbBpmnInventory {
  process_id: string; bpmn_file: string; sha256: string;
  service_tasks: string[]; user_tasks: string[]; gateways: string[]; task_names: Record<string, string>;
}
export interface OnbStagedArtifact { artifact_key: string; version: string; title: string; json_schema: Record<string, unknown>; source_tool?: string | null; }
export interface OnbStagedCapability {
  capability_id: string; version: string; title: string; side_effect: string; idempotent?: boolean | null;
  min_hitl_mode?: string | null; input_artifact_key: string; output_artifact_key: string;
  endpoint: string; tool: string; transport: string;
}
export interface OnbBindingIO { name: string; schema_ref: string; required: boolean; }
export interface OnbStagedBinding {
  element_id: string; element_kind: string; executor_type: string; capability_ref?: string | null;
  role?: string | null; hitl_mode: string; hitl_role?: string | null;
  inputs: OnbBindingIO[]; outputs: OnbBindingIO[];
}
export interface OnbTriageRule { rule_id: string; priority: number; description?: string | null; when: Record<string, unknown>; }
export interface OnbGatewayVariable { gateway_id: string; variable: string; source_artifact: string; }
export interface OnbSod { elements: string[]; }
export interface OnbRoleMeta { label?: string | null; description?: string | null; }
export interface OnbCommitStep { key: string; label: string; status: string; detail?: string | null; }

export interface OnboardingSession {
  session_id: string; created_by: string; created_at: string; updated_at: string; state: OnboardingState;
  basics: OnbBasics; bpmn?: OnbBpmnInventory | null;
  staged_artifacts: OnbStagedArtifact[]; staged_capabilities: OnbStagedCapability[]; reused_capability_refs: string[];
  bindings: OnbStagedBinding[]; triage_rules: OnbTriageRule[]; gateway_variables: OnbGatewayVariable[];
  sod_policies: OnbSod[]; roles: string[]; role_meta?: Record<string, OnbRoleMeta>;
  dry_run_report?: ValidationReport | null; commit_progress: OnbCommitStep[];
  result_pack?: string | null; last_cleared: string[];
}

export interface ToolCompliance { compliant: boolean; reasons: string[]; }
export interface IntrospectedTool {
  name: string; description?: string | null;
  input_schema?: Record<string, unknown> | null; output_schema?: Record<string, unknown> | null;
  compliance: ToolCompliance;
  suggested_input_artifact_key?: string | null;
  suggested_output_artifact_key?: string | null;
  suggested_capability_id?: string | null;
}
export interface IntrospectMcpResponse { endpoint: string; transport: string; tools: IntrospectedTool[]; }

export interface CapabilityToolSelection {
  tool: string; endpoint: string; transport?: string; headers?: Record<string, string>; domain?: string;
  input_artifact_key?: string; output_artifact_key?: string; capability_id?: string;
  artifact_version?: string; capability_version?: string; side_effect?: string; idempotent?: boolean | null;
  min_hitl_mode?: string | null; input_schema?: Record<string, unknown> | null; output_schema?: Record<string, unknown> | null;
  title?: string; description?: string;
}
export interface BindingInput {
  element_id: string; element_kind: string; executor_type: string; capability_ref?: string | null;
  role?: string | null; assist_capability_ref?: string | null; hitl_mode: string; hitl_role?: string | null;
}

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
export function setOnboardingCapabilities(id: string, body: { tools: CapabilityToolSelection[]; reused_capability_refs: string[] }): Promise<OnboardingSession> {
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
