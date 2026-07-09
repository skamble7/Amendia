import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, KeyRound, Plus, ShieldCheck, UserCog, X } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { EmptyState } from "@/components/primitives";
import { ConnectivityState } from "@/components/ConnectivityState";
import { isConnectivityError } from "@/api/client";
import { formatDateTime } from "@/lib/format";
import { ROLE, isAdminRole, roleDescription } from "@/lib/roles";
import { useCurrentIdentity } from "@/session/IdentityContext";
import { CopyableId, RoleBadge, UserStatusBadge } from "./AdminBits";
import { AssignRoleDialog } from "./AssignRoleDialog";
import { AccountStatusDialog } from "./AccountStatusDialog";
import { useRevokeRole, useUser, useUsers } from "./queries";

export function UserDetailPage() {
  const { userId } = useParams<{ userId: string }>();
  const me = useCurrentIdentity();
  const { data: user, isLoading, error } = useUser(userId);
  // Active-admin population drives the last-admin guardrail on the client (the
  // server's 409 remains the source of truth).
  const { data: adminHolders } = useUsers({ role: ROLE.platformAdmin, status: "active" });
  const activeAdminCount = (adminHolders ?? []).length;

  const revoke = useRevokeRole();
  const [assignOpen, setAssignOpen] = useState(false);
  const [statusOpen, setStatusOpen] = useState(false);

  const isSelf = !!user && user.amendia_user_id === me.amendiaUserId;
  const roles = user?.roles ?? [];
  const userIsActiveAdmin = !!user && user.status === "active" && roles.includes(ROLE.platformAdmin);
  const isLastActiveAdmin = userIsActiveAdmin && activeAdminCount <= 1;

  const details = useMemo(() => {
    const rs = user?.roles ?? [];
    const map = new Map((user?.role_details ?? []).map((d) => [d.role, d]));
    return rs.map((r) => map.get(r) ?? { role: r, assigned_by: null, assigned_at: null });
  }, [user]);

  if (isConnectivityError(error)) return <ConnectivityState error={error} />;

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (!user) {
    return (
      <EmptyState
        icon={<UserCog className="size-6" />}
        title="User not found"
        description="This user id doesn't exist. They may not have signed in yet."
        action={
          <Button asChild variant="outline">
            <Link to="/admin/users">Back to users</Link>
          </Button>
        }
      />
    );
  }

  const disabled = user.status === "disabled";
  const name = user.display_name ?? user.email ?? user.amendia_user_id;

  // Reason a control is locked, or null when it's allowed.
  const revokeAdminLock = isSelf
    ? "You can't revoke your own platform-admin role."
    : isLastActiveAdmin
      ? "At least one active platform admin must remain."
      : null;
  const disableLock = isSelf
    ? "You can't disable your own account."
    : isLastActiveAdmin
      ? "At least one active platform admin must remain."
      : null;

  return (
    <div className="space-y-5">
      <Link
        to="/admin/users"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" /> Users
      </Link>

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1.5">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-semibold tracking-tight">{name}</h1>
            <UserStatusBadge status={user.status} />
          </div>
          <p className="text-sm text-muted-foreground">{user.email ?? "No email on record"}</p>
          <CopyableId value={user.amendia_user_id} className="-ml-1.5" />
        </div>
      </div>

      {/* Roles */}
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="size-4 text-muted-foreground" /> Roles
          </CardTitle>
          <Button size="sm" onClick={() => setAssignOpen(true)}>
            <Plus className="size-4" /> Assign role
          </Button>
        </CardHeader>
        <CardContent>
          {details.length === 0 ? (
            <div className="rounded-md border border-dashed border-border bg-surface/40 px-4 py-8 text-center">
              <p className="text-sm font-medium">No roles assigned</p>
              <p className="mt-1 text-sm text-muted-foreground">
                This user can sign in but can't do anything yet. Assign a role to grant access.
              </p>
              <Button size="sm" className="mt-3" onClick={() => setAssignOpen(true)}>
                <Plus className="size-4" /> Assign a role
              </Button>
            </div>
          ) : (
            <ul className="divide-y divide-border">
              {details.map((d) => {
                const lock = isAdminRole(d.role) ? revokeAdminLock : null;
                return (
                  <li key={d.role} className="flex items-start justify-between gap-4 py-3 first:pt-0 last:pb-0">
                    <div className="min-w-0 space-y-1">
                      <div className="flex items-center gap-2">
                        <RoleBadge role={d.role} />
                      </div>
                      <p className="text-sm text-muted-foreground">{roleDescription(d.role)}</p>
                      {d.assigned_by && (
                        <p className="text-xs text-muted-foreground">
                          Assigned by <span className="font-mono">{d.assigned_by}</span>
                          {d.assigned_at ? ` · ${formatDateTime(d.assigned_at)}` : ""}
                        </p>
                      )}
                    </div>
                    <LockableButton
                      lock={lock}
                      onClick={() => revoke.mutate({ userId: user.amendia_user_id, role: d.role })}
                      disabled={revoke.isPending}
                      variant="ghost"
                      size="sm"
                      className="text-danger hover:text-danger"
                    >
                      <X className="size-4" /> Revoke
                    </LockableButton>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* Identities */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <KeyRound className="size-4 text-muted-foreground" /> Identities
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <ul className="space-y-2">
            {user.identities.map((idn, i) => (
              <li key={`${idn.iss}:${idn.sub}`} className="rounded-md border border-border bg-surface/40 p-3">
                <div className="grid gap-1 text-xs">
                  <div className="flex gap-2">
                    <span className="w-10 shrink-0 text-muted-foreground">iss</span>
                    <span className="break-all font-mono">{idn.iss}</span>
                  </div>
                  <div className="flex gap-2">
                    <span className="w-10 shrink-0 text-muted-foreground">sub</span>
                    <span className="break-all font-mono">{idn.sub}</span>
                  </div>
                </div>
                {i === 0 && user.identities.length === 1 && (
                  <span className="sr-only">primary identity</span>
                )}
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted-foreground">
            Identities link this user to your identity provider. Re-linking or merging identities is
            API-only in this release.
          </p>
        </CardContent>
      </Card>

      {/* Account */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <UserCog className="size-4 text-muted-foreground" /> Account
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            {disabled
              ? "This account is disabled — all its requests are refused until re-enabled."
              : "Disabling blocks this user from every Amendia service without deleting anything."}
          </p>
          {disabled ? (
            <Button variant="outline" onClick={() => setStatusOpen(true)}>
              Enable account
            </Button>
          ) : (
            <LockableButton lock={disableLock} variant="destructive" onClick={() => setStatusOpen(true)}>
              Disable account
            </LockableButton>
          )}
        </CardContent>
      </Card>

      <AssignRoleDialog
        userId={user.amendia_user_id}
        userName={name}
        existingRoles={roles}
        open={assignOpen}
        onOpenChange={setAssignOpen}
      />
      <AccountStatusDialog
        userId={user.amendia_user_id}
        userName={name}
        disable={!disabled}
        open={statusOpen}
        onOpenChange={setStatusOpen}
      />
    </div>
  );
}

/**
 * A button that renders disabled with an explanatory tooltip when `lock` is set
 * (the guardrail UX), and normally otherwise. The disabled element is wrapped in a
 * focusable span so the tooltip still shows.
 */
function LockableButton({
  lock,
  children,
  ...props
}: { lock: string | null } & React.ComponentProps<typeof Button>) {
  if (!lock) return <Button {...props}>{children}</Button>;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={0} className="inline-flex">
          <Button {...props} disabled aria-disabled className="pointer-events-none">
            {children}
          </Button>
        </span>
      </TooltipTrigger>
      <TooltipContent>{lock}</TooltipContent>
    </Tooltip>
  );
}
