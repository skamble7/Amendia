import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Clock, UserCheck } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  buildAssignableRoles,
  isAdminRole,
  roleDescription,
  roleLabel,
  type AssignableRole,
} from "@/lib/roles";
import { usePacks, useRolesInUse } from "@/features/registry/queries";
import { RolePicker } from "./RolePicker";
import { errorDetail, useReplacePending, useStagePending } from "./queries";

export function StageAccessDialog({
  open,
  onOpenChange,
  mode,
  initialEmail = "",
  initialRoles = [],
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mode: "stage" | "edit";
  initialEmail?: string;
  initialRoles?: string[];
}) {
  const navigate = useNavigate();
  const stage = useStagePending();
  const replace = useReplacePending();
  const rolesInUse = useRolesInUse();
  const packs = usePacks({ status: "active" });
  const pending = stage.isPending || replace.isPending;

  const [email, setEmail] = useState(initialEmail);
  const [roles, setRoles] = useState<string[]>(initialRoles);
  const [existing, setExisting] = useState<{ id: string; email: string } | null>(null);

  // Re-seed the form whenever the dialog (re)opens.
  useEffect(() => {
    if (open) {
      setEmail(initialEmail);
      setRoles(initialRoles);
      setExisting(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Platform roles + roles active packs reference, plus any already-selected id not in the
  // catalog (a custom role the admin added, or a legacy staged grant) so it still renders.
  const catalog = useMemo<AssignableRole[]>(() => {
    const base = buildAssignableRoles(rolesInUse.data ?? []);
    const extra: AssignableRole[] = roles
      .filter((id) => !base.some((o) => o.id === id))
      .map((id) => ({ id, label: roleLabel(id), description: roleDescription(id), isAdmin: isAdminRole(id) }));
    return [...base, ...extra];
  }, [rolesInUse.data, roles]);

  const packTitles = useMemo(
    () => Object.fromEntries((packs.data ?? []).map((p) => [p.pack_key, p.title])),
    [packs.data],
  );

  function toggle(role: string) {
    setRoles((prev) => (prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role]));
  }

  function addCustom(id: string) {
    setRoles((prev) => (prev.includes(id) ? prev : [...prev, id]));
  }

  const emailValid = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim());
  const canSubmit = roles.length > 0 && (mode === "edit" || emailValid) && !pending;

  function submit() {
    if (mode === "edit") {
      replace.mutate(
        { email: initialEmail, roles },
        { onSuccess: () => onOpenChange(false) },
      );
      return;
    }
    setExisting(null);
    stage.mutate(
      { email: email.trim(), roles },
      {
        onSuccess: () => onOpenChange(false),
        onError: (err) => {
          const detail = errorDetail(err);
          if (detail?.error === "user_exists" && detail.amendia_user_id) {
            setExisting({ id: detail.amendia_user_id, email: detail.email ?? email.trim() });
          }
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{mode === "edit" ? "Edit staged access" : "Stage access"}</DialogTitle>
          <DialogDescription>
            {mode === "edit"
              ? "Update the roles that will be granted when this person first signs in."
              : "Grant roles to someone before they sign in. The roles attach automatically the first time they authenticate with your identity provider."}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-1.5">
          <Label htmlFor="stage-email">Email</Label>
          <Input
            id="stage-email"
            type="email"
            placeholder="person@your-org.com"
            value={email}
            disabled={mode === "edit"}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="off"
          />
          {mode === "stage" && (
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Clock className="size-3" /> Activates on first sign-in — must match the address their IdP asserts.
            </p>
          )}
        </div>

        <div className="space-y-1.5">
          <Label>Roles</Label>
          <RolePicker
            mode="multi"
            catalog={catalog}
            selected={roles}
            onToggle={toggle}
            onAddCustom={addCustom}
            packTitles={packTitles}
          />
        </div>

        {existing && (
          <div className="flex items-start gap-2 rounded-md border border-attention/40 bg-attention-muted/40 p-3 text-xs text-attention">
            <UserCheck className="mt-0.5 size-4 shrink-0" />
            <div className="space-y-2">
              <p>
                <span className="font-mono">{existing.email}</span> already belongs to a provisioned
                user. Assign roles on their profile instead.
              </p>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  onOpenChange(false);
                  navigate(`/admin/users/${existing.id}`);
                }}
              >
                Go to user <ArrowRight className="size-3" />
              </Button>
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={!canSubmit}>
            {pending ? "Saving…" : mode === "edit" ? "Save changes" : "Stage access"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
