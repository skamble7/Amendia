import { request } from "../client";
import { SERVICE_BASE } from "../config";
import type { StoredException, GenerateRequest, GenerateResponse } from "../types";

export interface ExceptionFilters {
  exception_type?: string;
  status?: string;
  reason_code?: string;
  limit?: number;
  offset?: number;
}

export function listExceptions(filters: ExceptionFilters = {}, signal?: AbortSignal): Promise<StoredException[]> {
  return request<StoredException[]>("stub", "/exceptions", { query: { ...filters }, signal });
}

export function getException(exceptionId: string, signal?: AbortSignal): Promise<StoredException> {
  return request<StoredException>("stub", `/exceptions/${exceptionId}`, { signal });
}

/** Dev-only generator (design's "Generate exception" button). reason_code ∈ AC01|AC04|RC01|BE04. */
export function generateException(body: GenerateRequest): Promise<GenerateResponse> {
  return request<GenerateResponse>("stub", "/exceptions/generate", { method: "POST", body });
}

// ---- Domain-neutral trigger generators (discovery catalog) ------------------
export interface GeneratorScenario { id: string; label: string; body: Record<string, unknown>; }
export interface Generator { id: string; label: string; endpoint: string; scenarios: GeneratorScenario[]; }
export interface GeneratorCatalog { generators: Generator[]; }

/** The stub's catalog of trigger sources — each with the POST endpoint that raises it + its demo scenarios.
 *  The UI drives triggers from this instead of hardcoding any domain (reason codes, ticket flags, …). */
export function listGenerators(signal?: AbortSignal): Promise<GeneratorCatalog> {
  return request<GeneratorCatalog>("stub", "/generators", { signal });
}

/** One generated trigger's shape is domain-specific; only the id fields differ (exception vs ticket). */
export interface GenerateTriggerResult {
  created?: Array<{ exception?: { exception_id?: string }; ticket?: { ticket_id?: string } }>;
}

/** POST a scenario body to a generator's advertised stub endpoint (e.g. /exceptions/generate, /tickets/generate). */
export function generateTrigger(endpoint: string, body: unknown): Promise<GenerateTriggerResult> {
  return request<GenerateTriggerResult>("stub", endpoint, { method: "POST", body });
}

/** Direct URL for an attachment (rendered as <a>/<img> src, not fetched as JSON). */
export function attachmentUrl(exceptionId: string, attachmentId: string): string {
  const base = SERVICE_BASE.stub.replace(/\/$/, "");
  return `${base}/exceptions/${exceptionId}/attachments/${attachmentId}`;
}
