import { createContext, useContext, useMemo, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "react-oidc-context";
import { getMe } from "@/api/services/identity";
import { ApiError } from "@/api/client";

/** The Amendia identity, hydrated from GET /me — the UI's single identity source. */
export interface Identity {
  amendiaUserId: string;
  displayName: string;
  email: string | null;
  roles: string[];
}

interface IdentityValue {
  identity: Identity | null;
  /** authenticated, but /me hasn't resolved yet */
  isLoading: boolean;
  /** /me returned 403 user_disabled */
  isDisabled: boolean;
  error: ApiError | null;
  hasRole: (role: string) => boolean;
  refetch: () => void;
}

/** Exported for tests, which provide a synchronous identity value directly. */
export const IdentityContext = createContext<IdentityValue | null>(null);

function isDisabledError(err: unknown): boolean {
  return (
    err instanceof ApiError &&
    err.status === 403 &&
    typeof err.detail === "object" &&
    err.detail !== null &&
    (err.detail as { error?: string }).error === "user_disabled"
  );
}

export function IdentityProvider({ children }: { children: ReactNode }) {
  const auth = useAuth();

  const query = useQuery({
    queryKey: ["me"],
    queryFn: ({ signal }) => getMe(signal),
    enabled: auth.isAuthenticated,
    staleTime: Infinity, // cached for the session
    refetchOnWindowFocus: true, // pick up role changes promptly
    retry: false,
  });

  const { data, error: queryError, isLoading: queryLoading, refetch } = query;
  const value = useMemo<IdentityValue>(() => {
    const identity: Identity | null = data
      ? {
          amendiaUserId: data.amendia_user_id,
          displayName: data.display_name ?? data.email ?? data.amendia_user_id,
          email: data.email ?? null,
          roles: data.roles ?? [],
        }
      : null;
    return {
      identity,
      isLoading: auth.isAuthenticated && queryLoading,
      isDisabled: isDisabledError(queryError),
      error: (queryError as ApiError | null) ?? null,
      hasRole: (role: string) => identity?.roles.includes(role) ?? false,
      refetch: () => void refetch(),
    };
  }, [data, queryError, queryLoading, auth.isAuthenticated, refetch]);

  return <IdentityContext.Provider value={value}>{children}</IdentityContext.Provider>;
}

export function useIdentity(): IdentityValue {
  const ctx = useContext(IdentityContext);
  if (!ctx) throw new Error("useIdentity must be used within an IdentityProvider");
  return ctx;
}

/** The signed-in identity, or throws — use inside authenticated screens. */
export function useCurrentIdentity(): Identity {
  const { identity } = useIdentity();
  if (!identity) throw new Error("No resolved identity");
  return identity;
}
