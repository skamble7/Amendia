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
