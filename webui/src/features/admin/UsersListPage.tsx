import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Clock, Pencil, Search, Trash2, UserPlus, Users } from "lucide-react";
import { PageHeader } from "@/app/AppShell";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState, IdMono } from "@/components/primitives";
import { ConnectivityState } from "@/components/ConnectivityState";
import { isConnectivityError } from "@/api/client";
import { formatRelative, formatDateTime } from "@/lib/format";
import { ROLE } from "@/lib/roles";
import type { PendingView, UserView } from "@/api/services/identity";
import { RoleBadge, UserStatusBadge } from "./AdminBits";
import { StageAccessDialog } from "./StageAccessDialog";
import { useDeletePending, usePending, useUsers } from "./queries";

const NO_ROLES = "__none__";

const ROLE_FILTER_OPTIONS = [
  { value: "", label: "All roles" },
  { value: ROLE.analyst, label: "Analyst" },
  { value: ROLE.approver, label: "Approver" },
  { value: ROLE.processOwner, label: "Process owner" },
  { value: ROLE.platformAdmin, label: "Platform admin" },
  { value: NO_ROLES, label: "No roles" },
];

const selectClass =
  "h-9 rounded-md border border-input bg-transparent px-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function UsersListPage() {
  const [tab, setTab] = useState("users");

  return (
    <>
      <PageHeader title="Users" description="People and staged access in this Amendia deployment." />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="users">Users</TabsTrigger>
          <TabsTrigger value="pending">Pending access</TabsTrigger>
        </TabsList>
        <TabsContent value="users">
          <UsersTab />
        </TabsContent>
        <TabsContent value="pending">
          <PendingTab />
        </TabsContent>
      </Tabs>
    </>
  );
}

function UsersTab() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [roleFilter, setRoleFilter] = useState("");

  // The server filters by status + a concrete role; "no roles" is a client concern.
  const serverRole = roleFilter && roleFilter !== NO_ROLES ? roleFilter : undefined;
  const { data, isLoading, error } = useUsers({
    status: status || undefined,
    role: serverRole,
  });

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (data ?? []).filter((u) => {
      if (roleFilter === NO_ROLES && (u.roles ?? []).length > 0) return false;
      if (!q) return true;
      return (
        (u.display_name ?? "").toLowerCase().includes(q) ||
        (u.email ?? "").toLowerCase().includes(q) ||
        u.amendia_user_id.toLowerCase().includes(q)
      );
    });
  }, [data, search, roleFilter]);

  if (isConnectivityError(error)) return <ConnectivityState error={error} />;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name, email, or id"
            className="pl-8"
            aria-label="Search users"
          />
        </div>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className={selectClass}
          aria-label="Filter by status"
        >
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="disabled">Disabled</option>
        </select>
        <select
          value={roleFilter}
          onChange={(e) => setRoleFilter(e.target.value)}
          className={selectClass}
          aria-label="Filter by role"
        >
          {ROLE_FILTER_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      <div className="rounded-lg border border-border bg-surface">
        {isLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<Users className="size-6" />}
            title="No users match"
            description="Users are created the first time someone signs in. Adjust the filters or stage access under Pending access."
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>User</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Roles</TableHead>
                <TableHead>Identity</TableHead>
                <TableHead>First seen</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((u) => (
                <UserRow key={u.amendia_user_id} user={u} onOpen={() => navigate(`/admin/users/${u.amendia_user_id}`)} />
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  );
}

function UserRow({ user, onOpen }: { user: UserView; onOpen: () => void }) {
  const disabled = user.status === "disabled";
  const roles = user.roles ?? [];
  const iss = user.identities?.[0]?.iss;
  return (
    <TableRow
      className={disabled ? "cursor-pointer opacity-60" : "cursor-pointer"}
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => e.key === "Enter" && onOpen()}
    >
      <TableCell>
        <div className="font-medium">{user.display_name ?? user.email ?? user.amendia_user_id}</div>
        <div className="text-xs text-muted-foreground">{user.email ?? "—"}</div>
      </TableCell>
      <TableCell>
        <UserStatusBadge status={user.status} />
      </TableCell>
      <TableCell>
        {roles.length === 0 ? (
          <span className="text-xs text-muted-foreground">No roles</span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {roles.map((r) => (
              <RoleBadge key={r} role={r} />
            ))}
          </div>
        )}
      </TableCell>
      <TableCell>
        <IdMono value={iss} />
      </TableCell>
      <TableCell className="text-sm text-muted-foreground">{formatRelative(user.created_at)}</TableCell>
    </TableRow>
  );
}

function PendingTab() {
  const { data, isLoading, error } = usePending();
  const del = useDeletePending();
  const [stageOpen, setStageOpen] = useState(false);
  const [editing, setEditing] = useState<PendingView | null>(null);

  if (isConnectivityError(error)) return <ConnectivityState error={error} />;

  const rows = data ?? [];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="max-w-xl text-sm text-muted-foreground">
          Staged roles attach automatically the first time each person signs in. Until then they exist
          only here.
        </p>
        <Button onClick={() => setStageOpen(true)}>
          <UserPlus className="size-4" /> Stage access
        </Button>
      </div>

      <div className="rounded-lg border border-border bg-surface">
        {isLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<Clock className="size-6" />}
            title="No staged access"
            description="Stage roles for someone before they sign in — they'll be granted automatically at first login."
            action={
              <Button variant="outline" onClick={() => setStageOpen(true)}>
                <UserPlus className="size-4" /> Stage access
              </Button>
            }
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Email</TableHead>
                <TableHead>Staged roles</TableHead>
                <TableHead>Staged by</TableHead>
                <TableHead>Staged</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((p) => (
                <TableRow key={p.email} className="hover:bg-transparent">
                  <TableCell className="font-mono text-sm">{p.email}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {(p.roles ?? []).map((r) => (
                        <RoleBadge key={r} role={r} />
                      ))}
                    </div>
                  </TableCell>
                  <TableCell>
                    <IdMono value={p.staged_by} />
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground" title={formatDateTime(p.staged_at)}>
                    {formatRelative(p.staged_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button size="sm" variant="ghost" onClick={() => setEditing(p)}>
                        <Pencil className="size-4" /> Edit
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-danger hover:text-danger"
                        disabled={del.isPending}
                        onClick={() => del.mutate({ email: p.email })}
                      >
                        <Trash2 className="size-4" /> Remove
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      <StageAccessDialog open={stageOpen} onOpenChange={setStageOpen} mode="stage" />
      {editing && (
        <StageAccessDialog
          open={!!editing}
          onOpenChange={(o) => !o && setEditing(null)}
          mode="edit"
          initialEmail={editing.email}
          initialRoles={editing.roles ?? []}
        />
      )}
    </div>
  );
}
