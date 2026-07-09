import { useAuth } from "react-oidc-context";
import { Loader2, ShieldAlert, ServerCrash, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";

/** Full-screen calm loader for auth/identity in-flight states. */
export function FullScreenLoader({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        {label}
      </div>
    </div>
  );
}

/** GET /me → 403 user_disabled. */
export function AccountDisabled() {
  const auth = useAuth();
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-md space-y-4 text-center">
        <div className="mx-auto flex size-12 items-center justify-center rounded-xl bg-danger-muted text-danger">
          <ShieldAlert className="size-6" />
        </div>
        <h1 className="text-lg font-semibold">Account disabled</h1>
        <p className="text-sm text-muted-foreground">
          Your Amendia account is disabled. Contact your administrator to regain access.
        </p>
        <Button variant="outline" onClick={() => void auth.signoutRedirect()}>
          Sign out
        </Button>
      </div>
    </div>
  );
}

/**
 * Signed in, `/me` resolved, but the user holds zero roles — a calm "waiting for
 * access" state (not an error). This replaces the old behaviour of landing a
 * roleless user on an empty dashboard that fired 403s. Sign-out stays available.
 */
export function RolelessState({ displayName }: { displayName?: string }) {
  const auth = useAuth();
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-md space-y-4 text-center">
        <div className="mx-auto flex size-12 items-center justify-center rounded-xl bg-agent-muted text-agent">
          <Clock className="size-6" />
        </div>
        <h1 className="text-lg font-semibold">You're signed in{displayName ? `, ${displayName}` : ""}</h1>
        <p className="text-sm text-muted-foreground">
          Your account doesn't have any roles yet, so there's nothing to show. Ask your Amendia
          administrator to grant you access — once they do, sign in again and your workspace will be
          ready.
        </p>
        <Button variant="outline" onClick={() => void auth.signoutRedirect()}>
          Sign out
        </Button>
      </div>
    </div>
  );
}

/** /me couldn't be loaded for a non-auth reason (identity service down, 5xx). */
export function IdentityError({ onRetry }: { onRetry: () => void }) {
  const auth = useAuth();
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-md space-y-4 text-center">
        <div className="mx-auto flex size-12 items-center justify-center rounded-xl bg-attention-muted text-attention">
          <ServerCrash className="size-6" />
        </div>
        <h1 className="text-lg font-semibold">Couldn’t load your profile</h1>
        <p className="text-sm text-muted-foreground">
          The identity service didn’t respond. Check that the backend stack is running, then retry.
        </p>
        <div className="flex justify-center gap-2">
          <Button onClick={onRetry}>Retry</Button>
          <Button variant="outline" onClick={() => void auth.signoutRedirect()}>
            Sign out
          </Button>
        </div>
      </div>
    </div>
  );
}
