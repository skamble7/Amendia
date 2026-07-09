import { useEffect, useState } from "react";
import { ShieldAlert } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useSetUserStatus } from "./queries";

/**
 * Confirmation for disabling / enabling an account. Disable carries the design's
 * consequence copy and a required reason field (a deliberate friction gate — reason
 * capture is client-side only; there is no audit store for it yet).
 */
export function AccountStatusDialog({
  userId,
  userName,
  disable,
  open,
  onOpenChange,
}: {
  userId: string;
  userName: string;
  disable: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const setStatus = useSetUserStatus();
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (open) setReason("");
  }, [open]);

  function confirm() {
    setStatus.mutate({ userId, disable }, { onSuccess: () => onOpenChange(false) });
  }

  const canConfirm = (!disable || reason.trim().length > 0) && !setStatus.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{disable ? "Disable account" : "Enable account"}</DialogTitle>
          <DialogDescription>
            {disable ? (
              <>
                <span className="font-medium text-foreground">{userName}</span> will be blocked from
                every Amendia service — all their requests resolve to 403 and any active session stops
                working — until you re-enable them. Their roles and history are preserved.
              </>
            ) : (
              <>
                <span className="font-medium text-foreground">{userName}</span> will regain access with
                their existing roles.
              </>
            )}
          </DialogDescription>
        </DialogHeader>

        {disable && (
          <>
            <div className="flex items-start gap-2 rounded-md border border-danger/40 bg-danger-muted/40 p-3 text-xs text-danger">
              <ShieldAlert className="mt-0.5 size-4 shrink-0" />
              <p>This does not delete the account — it revokes access. Re-enable at any time.</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="disable-reason">Reason</Label>
              <Textarea
                id="disable-reason"
                placeholder="Why is this account being disabled?"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </div>
          </>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={setStatus.isPending}>
            Cancel
          </Button>
          <Button
            variant={disable ? "destructive" : "default"}
            onClick={confirm}
            disabled={!canConfirm}
          >
            {setStatus.isPending
              ? disable
                ? "Disabling…"
                : "Enabling…"
              : disable
                ? "Disable account"
                : "Enable account"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
