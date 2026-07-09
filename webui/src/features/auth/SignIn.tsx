import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "react-oidc-context";
import { Building2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

/**
 * Screen 0 — sign-in. The only path in is "Continue with your organization",
 * which starts the OIDC Authorization Code + PKCE redirect. In dev the IdP is the
 * bundled Keycloak; in production this goes to the customer's own IAM (their MFA,
 * their policies). The pre-login location is stashed in the OIDC `state` so deep
 * links survive the round-trip (restored in /auth/callback).
 */
export function SignIn() {
  const auth = useAuth();
  const location = useLocation();
  const rawFrom = (location.state as { from?: string } | null)?.from;
  const from = rawFrom ?? "/dashboard";

  // Already signed in (e.g. hitting /signin directly) → go where they meant to be.
  if (auth.isAuthenticated) return <Navigate to={from} replace />;

  const sessionEnded = Boolean(rawFrom) || Boolean(auth.error);
  const signIn = () => void auth.signinRedirect({ state: from });

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-md space-y-8">
        <header className="space-y-2 text-center">
          <div className="mx-auto flex size-12 items-center justify-center rounded-xl bg-agent-muted text-agent">
            <span className="text-lg font-semibold">A</span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">Amendia</h1>
          <p className="text-sm text-muted-foreground">Agentic payment-exception operations</p>
          <div className="flex items-center justify-center gap-2 pt-1">
            <Badge variant="outline">bank-alpha</Badge>
            <Badge variant="outline">{import.meta.env.DEV ? "development" : "production"}</Badge>
          </div>
        </header>

        <Button className="w-full justify-center" onClick={signIn} disabled={auth.isLoading}>
          {auth.isLoading ? <Loader2 className="size-4 animate-spin" /> : <Building2 className="size-4" />}
          Continue with your organization
        </Button>

        {sessionEnded ? (
          <p className="text-center text-sm text-muted-foreground">
            Your session ended — sign in to continue.
          </p>
        ) : (
          <p className="text-center text-xs text-muted-foreground">
            You’ll be redirected to your organization’s sign-in.
          </p>
        )}

        {auth.error && (
          <p className="text-center text-xs text-danger">{auth.error.message}</p>
        )}
      </div>
    </div>
  );
}
