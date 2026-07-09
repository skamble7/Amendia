import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "react-oidc-context";
import {
  LayoutDashboard,
  Inbox,
  Workflow,
  AlertTriangle,
  Boxes,
  ShieldCheck,
  ChevronsUpDown,
  LogOut,
} from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useIdentity } from "@/session/IdentityContext";
import { ROLE, OPERATOR_ROLES, rolesSummary } from "@/lib/roles";
import { cn } from "@/lib/utils";
import { ThemeMenu } from "@/app/ThemeMenu";

interface NavItem {
  to: string;
  label: string;
  icon: typeof LayoutDashboard;
  /** shown only if the user holds this role */
  requiresRole?: string;
  /** shown only if the user holds at least one of these roles */
  requiresAnyRole?: string[];
}

const NAV: NavItem[] = [
  // Operator surfaces — visible to anyone with an operator role. This keeps every
  // existing persona's nav identical (analyst/approver/process-owner are operators)
  // while a platform-admin-only user (alex) sees just Administration.
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard, requiresAnyRole: OPERATOR_ROLES },
  { to: "/inbox", label: "Task inbox", icon: Inbox, requiresAnyRole: OPERATOR_ROLES },
  { to: "/instances", label: "Instances", icon: Workflow, requiresAnyRole: OPERATOR_ROLES },
  { to: "/exceptions", label: "Exceptions", icon: AlertTriangle, requiresAnyRole: OPERATOR_ROLES },
  // Registry (process authoring) is process-owner only — progressive disclosure.
  { to: "/registry", label: "Registry", icon: Boxes, requiresRole: ROLE.processOwner },
  // Administration (users & roles) is platform-admin only — same mechanism.
  { to: "/admin/users", label: "Administration", icon: ShieldCheck, requiresRole: ROLE.platformAdmin },
];

/** Initials from a display name, e.g. "Riya Sharma" → "RS". */
function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map((p) => p[0]?.toUpperCase() ?? "").join("") || "?";
}

export function AppShell() {
  const auth = useAuth();
  const { identity, hasRole } = useIdentity();
  const nav = NAV.filter((n) => {
    if (n.requiresRole && !hasRole(n.requiresRole)) return false;
    if (n.requiresAnyRole && !n.requiresAnyRole.some((r) => hasRole(r))) return false;
    return true;
  });
  const initials = identity ? initialsOf(identity.displayName) : "?";

  return (
    <div className="flex min-h-screen bg-background">
      {/* Sidebar */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-surface md:flex">
        <div className="flex h-14 items-center gap-2 border-b border-border px-5">
          <div className="flex size-7 items-center justify-center rounded-lg bg-agent-muted text-agent">
            <span className="text-sm font-semibold">A</span>
          </div>
          <span className="font-semibold tracking-tight">Amendia</span>
        </div>
        <nav className="flex-1 space-y-0.5 p-3">
          {nav.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                )
              }
            >
              <Icon className="size-4" />
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between border-b border-border bg-surface/60 px-5 backdrop-blur">
          {/* Mobile nav fallback */}
          <nav className="flex items-center gap-1 md:hidden">
            {nav.map(({ to, icon: Icon, label }) => (
              <NavLink
                key={to}
                to={to}
                aria-label={label}
                className={({ isActive }) =>
                  cn("rounded-md p-2", isActive ? "bg-accent text-accent-foreground" : "text-muted-foreground")
                }
              >
                <Icon className="size-4" />
              </NavLink>
            ))}
          </nav>
          <div className="hidden md:block" />

          {identity && (
            <DropdownMenu>
              <DropdownMenuTrigger className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <Avatar className="size-7">
                  <AvatarFallback className="bg-agent-muted text-agent text-xs">{initials}</AvatarFallback>
                </Avatar>
                <span className="hidden text-left sm:block">
                  <span className="block leading-tight">{identity.displayName}</span>
                  <span className="block text-xs leading-tight text-muted-foreground">{rolesSummary(identity.roles)}</span>
                </span>
                <ChevronsUpDown className="size-4 text-muted-foreground" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-64">
                <DropdownMenuLabel>
                  <span className="block">{identity.displayName}</span>
                  {identity.email && (
                    <span className="block text-xs font-normal text-muted-foreground">{identity.email}</span>
                  )}
                  <span className="mt-1 block text-xs font-normal text-muted-foreground">{rolesSummary(identity.roles)}</span>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <ThemeMenu />
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => void auth.signoutRedirect()}>
                  <LogOut className="size-4" /> Sign out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </header>

        <main className="min-w-0 flex-1 overflow-auto">
          <div className="mx-auto w-full max-w-[1400px] p-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

/** Reusable page header used by feature screens. */
export function PageHeader({
  title,
  description,
  actions,
  badge,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  badge?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          {badge}
        </div>
        {description && <p className="text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
