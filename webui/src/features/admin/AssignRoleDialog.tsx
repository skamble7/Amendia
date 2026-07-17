import { useMemo, useState } from "react";
import { AlertTriangle } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import {
  buildAssignableRoles,
  isAdminRole,
  roleDescription,
  roleLabel,
  type AssignableRole,
} from "@/lib/roles";
import { usePacks, useRolesInUse } from "@/features/registry/queries";
import { RolePicker } from "./RolePicker";
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
  const rolesInUse = useRolesInUse();
  const packs = usePacks({ status: "active" });
  const [selected, setSelected] = useState<string | null>(null);
  // Custom `role.*` ids the admin typed (a pack that isn't active yet); rendered as cards too.
  const [customRoles, setCustomRoles] = useState<string[]>([]);

  // Platform roles + roles active packs reference + any typed customs. Roles the user already
  // holds stay in the catalog (marked "granted") so their pack doesn't vanish from the rail.
  const catalog = useMemo<AssignableRole[]>(() => {
    const base = buildAssignableRoles(rolesInUse.data ?? []);
    const extra: AssignableRole[] = customRoles
      .filter((id) => !base.some((o) => o.id === id))
      .map((id) => ({ id, label: roleLabel(id), description: roleDescription(id), isAdmin: isAdminRole(id) }));
    return [...base, ...extra];
  }, [rolesInUse.data, customRoles]);

  const packTitles = useMemo(
    () => Object.fromEntries((packs.data ?? []).map((p) => [p.pack_key, p.title])),
    [packs.data],
  );

  function reset() {
    setSelected(null);
    setCustomRoles([]);
  }

  function addCustom(id: string) {
    setCustomRoles((prev) => (prev.includes(id) ? prev : [...prev, id]));
    setSelected(id);
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
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Assign a role</DialogTitle>
          <DialogDescription>
            Grant an entitlement to <span className="font-medium text-foreground">{userName}</span>.
            Pick a pack on the left, then a role. Changes take effect on their next request.
          </DialogDescription>
        </DialogHeader>

        <RolePicker
          mode="single"
          catalog={catalog}
          selected={selected ? [selected] : []}
          onToggle={(id) => setSelected(id)}
          onAddCustom={addCustom}
          disabledIds={existingRoles}
          packTitles={packTitles}
        />

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
