import { request } from "../client";
import type { IngestionRecord } from "../types";

export interface IngestionFilters {
  exception_type?: string;
  status?: string;
  limit?: number;
  offset?: number;
}

export function listIngestions(filters: IngestionFilters = {}, signal?: AbortSignal): Promise<IngestionRecord[]> {
  return request<IngestionRecord[]>("ingestor", "/ingestions", { query: { ...filters }, signal });
}

export function getIngestion(exceptionId: string, signal?: AbortSignal): Promise<IngestionRecord> {
  return request<IngestionRecord>("ingestor", `/ingestions/${exceptionId}`, { signal });
}
