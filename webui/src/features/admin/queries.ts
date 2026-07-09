import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useApiQuery } from "@/api/live";
import { ApiError } from "@/api/client";
import {
  listUsers,
  getUser,
  assignRole,
  revokeRole,
  disableUser,
  enableUser,
  listPending,
  stagePending,
  replacePending,
  deletePending,
  type UserFilters,
} from "@/api/services/identity";
import { roleLabel } from "@/lib/roles";

// --------------------------------------------------------------------------- //
// Error-code helpers — the server's 409 codes are the source of truth for the
// guardrails, even when the client pre-disabled the control.
//
// This shape is deliberately hand-written here rather than in `api/gen/` : the
// identity service returns guardrail errors (`self_protection` / `last_admin` /
// `user_exists`) as FastAPI `HTTPException(detail={...})` dicts, which FastAPI does
// not model in its OpenAPI response schemas — so `openapi-typescript` can't emit a
// type for them. `gen/` stays 100% generator-owned; this lives with its consumer.
// --------------------------------------------------------------------------- //

export interface GuardDetail {
  error?: string;
  amendia_user_id?: string;
  email?: string;
  message?: string;
}

export function errorDetail(err: unknown): GuardDetail | null {
  if (err instanceof ApiError && err.detail && typeof err.detail === "object") {
    return err.detail as GuardDetail;
  }
  return null;
}

export function errorCode(err: unknown): string | undefined {
  return errorDetail(err)?.error;
}

const GUARD_MESSAGES: Record<string, string> = {
  self_protection: "You can't perform this action on your own account.",
  last_admin: "Refused — the platform must keep at least one active admin.",
};

/** Friendly toast for a mutation failure, honouring the server's guardrail codes. */
function toastGuardError(err: unknown, fallback: string) {
  const code = errorCode(err);
  if (code && GUARD_MESSAGES[code]) {
    toast.error(GUARD_MESSAGES[code]);
    return;
  }
  const msg = err instanceof ApiError ? err.detailText : fallback;
  toast.error(msg || fallback);
}

// --------------------------------------------------------------------------- //
// Queries
// --------------------------------------------------------------------------- //

export function useUsers(filters: UserFilters = {}) {
  return useApiQuery(["users", filters], (s) => listUsers(filters, s));
}

export function useUser(id: string | undefined) {
  return useApiQuery(["user", id], (s) => getUser(id!, s), { enabled: !!id });
}

export function usePending(emailFilter?: string) {
  return useApiQuery(["pending", emailFilter ?? ""], (s) => listPending(emailFilter, s));
}

// --------------------------------------------------------------------------- //
// Mutations — invalidate broadly; correctness over optimistic flash.
// --------------------------------------------------------------------------- //

function useInvalidateAdmin() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["users"] });
    qc.invalidateQueries({ queryKey: ["user"] });
    qc.invalidateQueries({ queryKey: ["pending"] });
    qc.invalidateQueries({ queryKey: ["me"] }); // caller may have changed their own state
  };
}

export function useAssignRole() {
  const invalidate = useInvalidateAdmin();
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) => assignRole(userId, role),
    onSuccess: (_d, { role }) => {
      toast.success(`Assigned ${roleLabel(role)}`);
      invalidate();
    },
    onError: (err) => toastGuardError(err, "Couldn't assign the role."),
  });
}

export function useRevokeRole() {
  const invalidate = useInvalidateAdmin();
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) => revokeRole(userId, role),
    onSuccess: (_d, { role }) => {
      toast.success(`Revoked ${roleLabel(role)}`);
      invalidate();
    },
    onError: (err) => toastGuardError(err, "Couldn't revoke the role."),
  });
}

export function useSetUserStatus() {
  const invalidate = useInvalidateAdmin();
  return useMutation({
    mutationFn: ({ userId, disable }: { userId: string; disable: boolean }) =>
      disable ? disableUser(userId) : enableUser(userId),
    onSuccess: (_d, { disable }) => {
      toast.success(disable ? "Account disabled" : "Account enabled");
      invalidate();
    },
    onError: (err) => toastGuardError(err, "Couldn't change the account status."),
  });
}

export function useStagePending() {
  const invalidate = useInvalidateAdmin();
  return useMutation({
    mutationFn: ({ email, roles }: { email: string; roles: string[] }) => stagePending(email, roles),
    onSuccess: (_d, { email }) => {
      toast.success(`Staged access for ${email}`);
      invalidate();
    },
    // Note: the caller inspects the `user_exists` 409 itself to offer a redirect,
    // so no toast here for that code — a generic fallback covers everything else.
    onError: (err) => {
      if (errorCode(err) === "user_exists") return;
      toastGuardError(err, "Couldn't stage access.");
    },
  });
}

export function useReplacePending() {
  const invalidate = useInvalidateAdmin();
  return useMutation({
    mutationFn: ({ email, roles }: { email: string; roles: string[] }) =>
      replacePending(email, roles),
    onSuccess: (_d, { email }) => {
      toast.success(`Updated staged access for ${email}`);
      invalidate();
    },
    onError: (err) => toastGuardError(err, "Couldn't update staged access."),
  });
}

export function useDeletePending() {
  const invalidate = useInvalidateAdmin();
  return useMutation({
    mutationFn: ({ email }: { email: string }) => deletePending(email),
    onSuccess: (_d, { email }) => {
      toast.success(`Removed staged access for ${email}`);
      invalidate();
    },
    onError: (err) => toastGuardError(err, "Couldn't remove staged access."),
  });
}
