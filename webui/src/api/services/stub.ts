import { request } from "../client";
import { SERVICE_BASE } from "../config";
import type { StoredTrigger } from "../types";

export interface TriggerFilters {
  trigger_type?: string;
  status?: string;
  limit?: number;
  offset?: number;
}

export function listTriggers(filters: TriggerFilters = {}, signal?: AbortSignal): Promise<StoredTrigger[]> {
  return request<StoredTrigger[]>("stub", "/triggers", { query: { ...filters }, signal });
}

export function getTrigger(triggerId: string, signal?: AbortSignal): Promise<StoredTrigger> {
  return request<StoredTrigger>("stub", `/triggers/${triggerId}`, { signal });
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

/** A generated trigger — the stub returns the stored envelope keyed under `trigger`. */
export interface GenerateTriggerResult {
  created?: Array<{ trigger?: { trigger_id?: string } }>;
}

/** POST a scenario body to a generator's advertised endpoint (e.g. /generators/wire/generate). */
export function generateTrigger(endpoint: string, body: unknown): Promise<GenerateTriggerResult> {
  return request<GenerateTriggerResult>("stub", endpoint, { method: "POST", body });
}

/** Direct URL for an attachment (rendered as <a>/<img> src, not fetched as JSON). */
export function attachmentUrl(triggerId: string, attachmentId: string): string {
  const base = SERVICE_BASE.stub.replace(/\/$/, "");
  return `${base}/triggers/${triggerId}/attachments/${attachmentId}`;
}
