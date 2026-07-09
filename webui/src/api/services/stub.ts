import { request } from "../client";
import { SERVICE_BASE } from "../config";
import type { StoredException, GenerateRequest, GenerateResponse } from "../types";

export interface ExceptionFilters {
  tenant?: string;
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

/** Direct URL for an attachment (rendered as <a>/<img> src, not fetched as JSON). */
export function attachmentUrl(exceptionId: string, attachmentId: string): string {
  const base = SERVICE_BASE.stub.replace(/\/$/, "");
  return `${base}/exceptions/${exceptionId}/attachments/${attachmentId}`;
}
