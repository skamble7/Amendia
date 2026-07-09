import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Check, Clock, UserCheck } from "lucide-react";
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
import { cn } from "@/lib/utils";
import { ASSIGNABLE_ROLES, roleDescription, roleLabel } from "@/lib/roles";
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

  function toggle(role: string) {
    setRoles((prev) => (prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role]));
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
      <DialogContent>
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
          <div className="grid gap-2">
            {ASSIGNABLE_ROLES.map((role) => {
              const active = roles.includes(role);
              return (
                <button
                  key={role}
                  type="button"
                  role="checkbox"
                  aria-checked={active}
                  onClick={() => toggle(role)}
                  className={cn(
                    "flex items-start gap-3 rounded-lg border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    active ? "border-primary bg-accent/50" : "border-border hover:bg-accent/40",
                  )}
                >
                  <span
                    className={cn(
                      "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded border",
                      active ? "border-primary bg-primary text-primary-foreground" : "border-input",
                    )}
                  >
                    {active && <Check className="size-3" />}
                  </span>
                  <span className="min-w-0 space-y-0.5">
                    <span className="block text-sm font-medium">{roleLabel(role)}</span>
                    <span className="block text-xs text-muted-foreground">{roleDescription(role)}</span>
                  </span>
                </button>
              );
            })}
          </div>
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
