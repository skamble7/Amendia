import { Navigate, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "react-oidc-context";
import { useIdentity } from "@/session/IdentityContext";
import { AccountDisabled, FullScreenLoader, IdentityError, RolelessState } from "@/features/auth/AuthStates";

/**
 * Route gate. Order of states:
 *  - auth resolving          → loader
 *  - unauthenticated         → /signin (remembering the intended deep link)
 *  - disabled account (/me 403) → account-disabled screen
 *  - /me still loading       → loader (app shell not shown until identity is known)
 *  - /me failed (non-auth)   → retryable identity-error screen
 *  - identity with zero roles → calm "no access yet" state (not the app shell)
 *  - authenticated + identity → the app
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const { identity, isLoading, isDisabled, error, refetch } = useIdentity();
  const location = useLocation();

  if (auth.isLoading) return <FullScreenLoader label="Checking your session…" />;

  if (!auth.isAuthenticated) {
    return <Navigate to="/signin" replace state={{ from: location.pathname + location.search }} />;
  }

  if (isDisabled) return <AccountDisabled />;
  if (isLoading) return <FullScreenLoader label="Loading your workspace…" />;
  if (!identity) return <IdentityError onRetry={refetch} />;
  void error; // non-disabled errors are surfaced by IdentityError above (identity is null)

  // Resolved but entitled to nothing → a calm waiting state, not the (empty) shell.
  if (identity.roles.length === 0) return <RolelessState displayName={identity.displayName} />;

  return <>{children}</>;
}
