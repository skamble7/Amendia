import { useMemo, useState } from "react";
import { AlertTriangle, Check } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ASSIGNABLE_ROLES, isAdminRole, roleDescription, roleLabel } from "@/lib/roles";
import { useAssignRole } from "./queries";

export function AssignRoleDialog({
  userId,
  userName,
  existingRoles,
  open,
  onOpenChange,
}: {
  userId: string;
  userName: string;
  existingRoles: string[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const assign = useAssignRole();
  const [selected, setSelected] = useState<string | null>(null);

  // Only roles the user doesn't already hold are assignable.
  const options = useMemo(
    () => ASSIGNABLE_ROLES.filter((r) => !existingRoles.includes(r)),
    [existingRoles],
  );

  function reset() {
    setSelected(null);
  }

  function confirm() {
    if (!selected) return;
    assign.mutate(
      { userId, role: selected },
      {
        onSuccess: () => {
          reset();
          onOpenChange(false);
        },
      },
    );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) reset();
        onOpenChange(o);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Assign a role</DialogTitle>
          <DialogDescription>
            Grant an entitlement to <span className="font-medium text-foreground">{userName}</span>.
            Changes take effect on their next request.
          </DialogDescription>
        </DialogHeader>

        {options.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            This user already holds every assignable role.
          </p>
        ) : (
          <div className="grid gap-2" role="radiogroup" aria-label="Role to assign">
            {options.map((role) => {
              const active = selected === role;
              const admin = isAdminRole(role);
              return (
                <button
                  key={role}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => setSelected(role)}
                  className={cn(
                    "flex items-start gap-3 rounded-lg border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    active
                      ? "border-primary bg-accent/50"
                      : "border-border hover:bg-accent/40",
                  )}
                >
                  <span
                    className={cn(
                      "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border",
                      active ? "border-primary bg-primary text-primary-foreground" : "border-input",
                    )}
                  >
                    {active && <Check className="size-3" />}
                  </span>
                  <span className="min-w-0 space-y-0.5">
                    <span className="flex items-center gap-2 text-sm font-medium">
                      {roleLabel(role)}
                      {admin && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-attention-muted px-1.5 py-0.5 text-xs font-medium text-attention">
                          <AlertTriangle className="size-3" /> Elevated
                        </span>
                      )}
                    </span>
                    <span className="block text-xs text-muted-foreground">{roleDescription(role)}</span>
                  </span>
                </button>
              );
            })}
          </div>
        )}

        {selected && isAdminRole(selected) && (
          <div className="flex items-start gap-2 rounded-md border border-attention/40 bg-attention-muted/40 p-3 text-xs text-attention">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            <p>
              Platform admin grants full control over users, roles, and staged access. Assign it only
              to people who should administer the platform.
            </p>
          </div>
        )}

        {selected && (
          <p className="text-xs text-muted-foreground">
            {roleLabel(selected)} will be granted to {userName} and recorded as assigned by you.
          </p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={assign.isPending}>
            Cancel
          </Button>
          <Button onClick={confirm} disabled={!selected || assign.isPending}>
            {assign.isPending ? "Assigning…" : "Assign role"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
