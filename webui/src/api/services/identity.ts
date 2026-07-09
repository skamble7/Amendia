import { request } from "../client";
import type { components } from "../gen/identity";

/** The caller's Amendia identity + roles — the UI's single identity source. */
export type Me = components["schemas"]["UserView"];
/** A user as returned by the admin list/detail endpoints. */
export type UserView = components["schemas"]["UserView"];
/** Staged (pending) access for an email that hasn't signed in yet. */
export type PendingView = components["schemas"]["PendingView"];

/**
 * GET /me — bearer-authenticated. 403 `{error: "user_disabled"}` for a disabled
 * account (handled by the identity context, not toasted).
 */
export function getMe(signal?: AbortSignal): Promise<Me> {
  return request<Me>("identity", "/me", { signal, silent: true });
}

export interface UserFilters {
  status?: string;
  role?: string;
}

/** GET /users — admin list, filterable by status/role (both optional). */
export function listUsers(filters: UserFilters = {}, signal?: AbortSignal): Promise<UserView[]> {
  return request<UserView[]>("identity", "/users", {
    query: { status: filters.status || undefined, role: filters.role || undefined },
    signal,
    silent: true,
  });
}

/** GET /users/{id} — one user + roles. */
export function getUser(id: string, signal?: AbortSignal): Promise<UserView> {
  return request<UserView>("identity", `/users/${encodeURIComponent(id)}`, { signal, silent: true });
}

/** POST /users/{id}/roles — assign a role (201; 409 already-held; 422 bad pattern). */
export function assignRole(id: string, role: string): Promise<UserView> {
  return request<UserView>("identity", `/users/${encodeURIComponent(id)}/roles`, {
    method: "POST",
    body: { role },
    silent: true,
  });
}

/** DELETE /users/{id}/roles/{role} — revoke (404 if absent; 409 self/last-admin). */
export function revokeRole(id: string, role: string): Promise<UserView> {
  return request<UserView>(
    "identity",
    `/users/${encodeURIComponent(id)}/roles/${encodeURIComponent(role)}`,
    { method: "DELETE", silent: true },
  );
}

/** POST /users/{id}/disable — flip to disabled (409 self/last-admin). */
export function disableUser(id: string): Promise<UserView> {
  return request<UserView>("identity", `/users/${encodeURIComponent(id)}/disable`, {
    method: "POST",
    silent: true,
  });
}

/** POST /users/{id}/enable — flip back to active. */
export function enableUser(id: string): Promise<UserView> {
  return request<UserView>("identity", `/users/${encodeURIComponent(id)}/enable`, {
    method: "POST",
    silent: true,
  });
}

// --------------------------------------------------------------------------- //
// Pending (staged) access
// --------------------------------------------------------------------------- //

/** GET /pending-role-assignments — staged access, optional email substring filter. */
export function listPending(email?: string, signal?: AbortSignal): Promise<PendingView[]> {
  return request<PendingView[]>("identity", "/pending-role-assignments", {
    query: { email: email || undefined },
    signal,
    silent: true,
  });
}

/** POST /pending-role-assignments — stage roles for an email (409 `user_exists`). */
export function stagePending(email: string, roles: string[]): Promise<PendingView> {
  return request<PendingView>("identity", "/pending-role-assignments", {
    method: "POST",
    body: { email, roles },
    silent: true,
  });
}

/** PUT /pending-role-assignments/{email} — replace the staged role set. */
export function replacePending(email: string, roles: string[]): Promise<PendingView> {
  return request<PendingView>(
    "identity",
    `/pending-role-assignments/${encodeURIComponent(email)}`,
    { method: "PUT", body: { roles }, silent: true },
  );
}

/** DELETE /pending-role-assignments/{email} — remove staged access (204). */
export function deletePending(email: string): Promise<void> {
  return request<void>("identity", `/pending-role-assignments/${encodeURIComponent(email)}`, {
    method: "DELETE",
    silent: true,
  });
}
