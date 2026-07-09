import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ShieldAlert } from "lucide-react";
import { EmptyState } from "@/components/primitives";
import { Button } from "@/components/ui/button";
import { useIdentity } from "@/session/IdentityContext";

/**
 * Client-side route gate for role-restricted screens (progressive disclosure — the
 * backend still enforces every request). A user who deep-links to a screen they
 * lack the role for gets a calm forbidden state instead of a failing page.
 */
export function RequireRole({ role, children }: { role: string; children: ReactNode }) {
  const { hasRole } = useIdentity();
  if (hasRole(role)) return <>{children}</>;
  return (
    <EmptyState
      icon={<ShieldAlert className="size-6" />}
      title="You don't have access to this area"
      description="This section requires a role your account doesn't hold. Ask your administrator if you need it."
      action={
        <Button asChild variant="outline">
          <Link to="/dashboard">Back to dashboard</Link>
        </Button>
      }
    />
  );
}
