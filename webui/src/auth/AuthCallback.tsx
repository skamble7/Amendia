import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "react-oidc-context";
import { Loader2, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * OIDC redirect landing. The provider processes the code exchange automatically;
 * this screen waits for it, then restores the pre-login deep link stashed in the
 * OIDC `state` so links into a specific task survive the round-trip.
 */
export function AuthCallback() {
  const auth = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (auth.isLoading) return;
    if (auth.isAuthenticated) {
      const returnTo = typeof auth.user?.state === "string" ? auth.user.state : "/dashboard";
      navigate(returnTo || "/dashboard", { replace: true });
    }
  }, [auth.isLoading, auth.isAuthenticated, auth.user, navigate]);

  if (auth.error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-4">
        <div className="w-full max-w-md space-y-4 text-center">
          <div className="mx-auto flex size-12 items-center justify-center rounded-xl bg-danger-muted text-danger">
            <AlertTriangle className="size-6" />
          </div>
          <h1 className="text-lg font-semibold">Sign-in couldn’t complete</h1>
          <p className="text-sm text-muted-foreground">{auth.error.message}</p>
          <Button onClick={() => navigate("/signin", { replace: true })}>Back to sign-in</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        Completing sign-in…
      </div>
    </div>
  );
}
