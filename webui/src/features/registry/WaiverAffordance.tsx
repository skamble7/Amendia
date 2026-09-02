// features/registry/WaiverAffordance.tsx
// ADR-065 P3 — the operator affordance for waiving the human gate on a side-effectful step. Shared by the
// technical wizard (Bindings) and the copilot stepped review (which reuses the same BindingsStep).
//
// The waiver is a WRITTEN justification (>= 20 chars after strip), never a checkbox: the friction IS the control,
// and the text is what lands in the audit trail. The copy states plainly that the step performs a real-world
// action and will run with NO human approval — it must not be softened. The contract + registry validator remain
// the authority; this client-side mirror is for feedback, not safety.
import { useState } from "react";
import { ShieldAlert, Pencil, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

/** Mirrors SideEffectWaiver.justification: the contract rejects anything under 20 chars after strip at parse time. */
export const WAIVER_MIN_CHARS = 20;

export type WaiverValue = { justification: string };

/** The capability id without its version range — matches `_bare_cap_id` in reconcile.py (compare on this). */
export function bareCapId(ref?: string | null): string | undefined {
  return ref ? ref.split("@")[0] : undefined;
}

export function WaiverAffordance({
  capabilityRef, waiver, onChange, disabled,
}: {
  capabilityRef?: string | null;
  waiver?: WaiverValue | null;
  onChange: (waiver: WaiverValue | null) => void;
  disabled?: boolean;
}) {
  const capId = bareCapId(capabilityRef) ?? "this capability";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(waiver?.justification ?? "");
  const trimmed = draft.trim();
  const ok = trimmed.length >= WAIVER_MIN_CHARS;

  // Waived, at rest — the loudest possible summary, plus edit / clear.
  if (waiver && !editing) {
    return (
      <div className="rounded-md border border-danger/50 bg-danger-muted/20 p-3" data-testid="waiver-active">
        <div className="flex items-start gap-2">
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-danger" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-danger">Runs with no human approval — waived</p>
            <p className="mt-1 text-xs text-muted-foreground">
              <span className="font-mono">{capId}</span> performs a real-world action and will run automatically,
              unsupervised.
            </p>
            <p className="mt-2 whitespace-pre-line border-l-2 border-danger/40 pl-2 text-xs italic text-foreground">
              “{waiver.justification}”
            </p>
          </div>
        </div>
        <div className="mt-2 flex gap-2">
          <Button size="sm" variant="outline" className="h-7 gap-1 text-xs" disabled={disabled}
            onClick={() => { setDraft(waiver.justification); setEditing(true); }}>
            <Pencil className="size-3" /> Edit justification
          </Button>
          <Button size="sm" variant="outline" className="h-7 gap-1 text-xs" disabled={disabled}
            onClick={() => onChange(null)}>
            <X className="size-3" /> Clear waiver (re-apply the gate)
          </Button>
        </div>
      </div>
    );
  }

  // Creating / editing the justification.
  if (editing) {
    return (
      <div className="rounded-md border border-danger/50 bg-danger-muted/10 p-3" data-testid="waiver-editor">
        <p className="flex items-center gap-1.5 text-sm font-medium text-danger">
          <ShieldAlert className="size-4" /> Waive the human gate on <span className="font-mono">{capId}</span>
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          <span className="font-mono">{capId}</span> performs a <span className="font-medium">real-world action</span>.
          Waiving lets it run with <span className="font-medium text-danger">no human approval</span>. Write why it is
          safe to run unsupervised — this justification is recorded in the audit trail.
        </p>
        <Textarea
          aria-label="waiver justification"
          className="mt-2 text-sm" rows={3} value={draft} autoFocus
          onChange={(e) => setDraft(e.target.value)}
          placeholder="e.g. Idempotent status handback to the orchestrator; a re-run is a no-op, nothing to approve." />
        <div className="mt-1 flex items-center justify-between">
          <span className={cn("text-xs", ok ? "text-muted-foreground" : "text-danger")}>
            {trimmed.length}/{WAIVER_MIN_CHARS} characters minimum
          </span>
          <div className="flex gap-2">
            <Button size="sm" variant="ghost" className="h-7 text-xs"
              onClick={() => { setEditing(false); setDraft(waiver?.justification ?? ""); }}>Cancel</Button>
            <Button size="sm" variant="destructive" className="h-7 text-xs" disabled={!ok}
              onClick={() => { onChange({ justification: trimmed }); setEditing(false); }}>
              Waive the gate
            </Button>
          </div>
        </div>
      </div>
    );
  }

  // Unwaived, collapsed — the entry affordance.
  return (
    <Button size="sm" variant="outline" className="h-7 gap-1 border-danger/40 text-xs text-danger"
      disabled={disabled} onClick={() => { setDraft(""); setEditing(true); }}>
      <ShieldAlert className="size-3" /> Waive the human gate…
    </Button>
  );
}
