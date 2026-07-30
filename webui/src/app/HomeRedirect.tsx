import { Navigate } from "react-router-dom";
import { useIdentity } from "@/session/IdentityContext";
import { isOperator, ROLE } from "@/lib/roles";

/**
 * Landing route ("/"): send operators to the dashboard and a platform-admin-only
 * user (no operator role) to Administration, so nobody lands on a screen that isn't
 * in their nav. Roleless users never reach here (RequireAuth intercepts them).
 */
export function HomeRedirect() {
  const { identity, hasRole } = useIdentity();
  if (!isOperator(identity?.roles ?? []) && hasRole(ROLE.platformAdmin)) {
    return <Navigate to="/admin/users" replace />;
  }
  return <Navigate to="/dashboard" replace />;
}
