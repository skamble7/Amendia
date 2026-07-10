import { request } from "../client";
import type {
  HitlTask,
  ProcessInstance,
  DecideRequest,
  InstanceDetail,
  InstanceState,
} from "../types";

// ---------------- HITL tasks ----------------

export interface HitlTaskFilters {
  status?: string;
  role?: string;
  process_instance_id?: string;
  exception_id?: string;
  limit?: number;
  offset?: number;
}

export function listHitlTasks(filters: HitlTaskFilters = {}, signal?: AbortSignal): Promise<HitlTask[]> {
  return request<HitlTask[]>("runtime", "/hitl-tasks", { query: { ...filters }, signal });
}

export function getHitlTask(taskId: string, signal?: AbortSignal): Promise<HitlTask> {
  return request<HitlTask>("runtime", `/hitl-tasks/${taskId}`, { signal });
}

/**
 * Claim a task. Identity comes from the bearer token — no body. 409 unless open,
 * 403 if SoD-excluded / wrong role — callers pass `silent` and handle.
 */
export function claimTask(taskId: string): Promise<HitlTask> {
  return request<HitlTask>("runtime", `/hitl-tasks/${taskId}/claim`, { method: "POST", silent: true });
}

/** Decide a task. 403 SoD/role, 409 wrong state, 400 edit re-validation — handled by callers. */
export function decideTask(taskId: string, body: DecideRequest): Promise<HitlTask> {
  return request<HitlTask>("runtime", `/hitl-tasks/${taskId}/decide`, { method: "POST", body, silent: true });
}

// ---------------- Instances ----------------

export interface InstanceFilters {
  exception_id?: string;
  status?: string;
  limit?: number;
  offset?: number;
}

export function listInstances(filters: InstanceFilters = {}, signal?: AbortSignal): Promise<ProcessInstance[]> {
  return request<ProcessInstance[]>("runtime", "/instances", { query: { ...filters }, signal });
}

export function getInstance(id: string, signal?: AbortSignal): Promise<InstanceDetail> {
  return request<InstanceDetail>("runtime", `/instances/${id}`, { signal });
}

/**
 * Flag-guarded checkpointed state. Returns null when the debug flag is off (404)
 * so callers can degrade gracefully with the design's explanatory note.
 */
export async function getInstanceState(id: string, signal?: AbortSignal): Promise<InstanceState | null> {
  try {
    return await request<InstanceState>("runtime", `/instances/${id}/state`, { signal, silent: true });
  } catch (err) {
    if ((err as { status?: number }).status === 404 || (err as { status?: number }).status === 503) return null;
    throw err;
  }
}

// ---------------- Registry read-mirrors on runtime (:8083) ----------------
// (Authoring lives on the registry service; these are the read views the app uses
//  when it only needs the active catalog without the write lifecycle.)
