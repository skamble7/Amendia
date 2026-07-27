import { Fragment, useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ArtifactView } from "@/components/artifact/ArtifactView";
import { ArtifactEditor } from "./ArtifactEditor";
import { CommentField, DecisionRow } from "./DecisionKit";
import type { DecideArgs } from "./useTaskActions";
import type { HitlTask, PayloadArtifact, ProposedAction } from "@/api/types";

export interface VariantProps {
  task: HitlTask;
  onDecide: (args: DecideArgs) => void;
  pending: boolean;
}

const artifactsOf = (task: HitlTask): PayloadArtifact[] => task.payload.artifacts ?? [];

// Payload artifacts carry runtime flags (`draft` / `authored_by_human`) that mark an OUTPUT the human authors,
// vs a read-only input context artifact. They aren't in the generated type, so read them defensively.
const isDraft = (a: PayloadArtifact): boolean => Boolean((a as Record<string, unknown>).draft);
const isAgentDraft = (a: PayloadArtifact): boolean =>
  isDraft(a) && !(a as Record<string, unknown>).authored_by_human;

function guardReject(comment: string, act: () => void) {
  if (!comment.trim()) {
    toast.error("A comment is required to reject.");
    return;
  }
  act();
}

// ---------------- Review (review_after) ----------------

export function ReviewVariant({ task, onDecide, pending }: VariantProps) {
  const artifacts = artifactsOf(task);
  const [editing, setEditing] = useState(false);
  const [comment, setComment] = useState("");
  const formId = `edit-${task.task_id}`;

  return (
    <div className="space-y-4">
      {!editing ? (
        <ArtifactEditor id={`view-${task.task_id}`} artifacts={artifacts} />
      ) : (
        <ArtifactEditor
          id={formId}
          artifacts={artifacts}
          onSubmit={(edits) => onDecide({ decision: "edit_and_approve", edits, comment })}
        />
      )}

      <CommentField value={comment} onChange={setComment} />

      {/* Distinct keys per action group so React UNMOUNTS one and MOUNTS the other, instead of reconciling the
          clicked node in place — the "Edit & approve" button (index 1) would otherwise be mutated into the
          "Save edits & approve" submit button and the browser would run the click's default submit against it. */}
      <DecisionRow>
        {editing ? (
          <Fragment key="editing-actions">
            <Button type="button" variant="ghost" onClick={() => setEditing(false)} disabled={pending}>
              Cancel edit
            </Button>
            <Button type="submit" form={formId} disabled={pending}>
              Save edits & approve
            </Button>
          </Fragment>
        ) : (
          <Fragment key="review-actions">
            <Button type="button" variant="destructive" onClick={() => guardReject(comment, () => onDecide({ decision: "reject", comment }))} disabled={pending}>
              Reject
            </Button>
            {/* preventDefault() cancels the click's default submit for THIS click, regardless of any in-place
                type mutation during React's re-render — the definitive per-click guard alongside the keys. */}
            <Button type="button" variant="outline" onClick={(e) => { e.preventDefault(); setEditing(true); }} disabled={pending}>
              Edit & approve
            </Button>
            <Button type="button" variant="success" onClick={() => onDecide({ decision: "approve", comment })} disabled={pending}>
              Approve
            </Button>
          </Fragment>
        )}
      </DecisionRow>
    </div>
  );
}

// ---------------- Approve result (approve_result) ----------------

export function ApproveResultVariant({ task, onDecide, pending }: VariantProps) {
  const [comment, setComment] = useState("");

  return (
    <div className="space-y-4">
      <ArtifactEditor id={`view-${task.task_id}`} artifacts={artifactsOf(task)} />
      <p className="text-xs text-muted-foreground">This result stands or falls as-is — it cannot be edited here.</p>
      <CommentField value={comment} onChange={setComment} />
      <DecisionRow>
        <Button type="button" variant="destructive" onClick={() => guardReject(comment, () => onDecide({ decision: "reject", comment }))} disabled={pending}>
          Reject
        </Button>
        <Button type="button" variant="success" onClick={() => onDecide({ decision: "approve", comment })} disabled={pending}>
          Approve
        </Button>
      </DecisionRow>
    </div>
  );
}

// ---------------- Authorize actions (approve_actions) ----------------

export function AuthorizeActionsVariant({ task, onDecide, pending }: VariantProps) {
  const actions = (task.payload.proposed_actions ?? []) as ProposedAction[];
  const [selected, setSelected] = useState<Set<string>>(new Set(actions.map((a) => a.action_id)));
  const [comment, setComment] = useState("");

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const allSelected = selected.size === actions.length;

  // Defensive (ADR-047 D2): a side-effectful approve_actions gate synthesizes ≥1 pending action host-side, so an
  // EMPTY list means the bound capability is mis-declared (e.g. read_only under approve_actions) — a pack/config
  // error, not something to authorize. Surface it plainly rather than presenting an un-clickable "Authorize"
  // that deadlocks the instance. Reject stays available; we never auto-approve.
  if (actions.length === 0) {
    return (
      <div className="space-y-4">
        <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" />
          <p>
            No actions were proposed for this authorization gate. This is a pack/configuration error (a
            side-effectful task must present the pending action). There is nothing to authorize — reject to
            unblock, and report the pack binding.
          </p>
        </div>
        <CommentField value={comment} onChange={setComment} required />
        <DecisionRow>
          <Button type="button" variant="destructive" onClick={() => guardReject(comment, () => onDecide({ decision: "reject", comment }))} disabled={pending}>
            Reject
          </Button>
        </DecisionRow>
      </div>
    );
  }

  function approve() {
    if (selected.size === 0) {
      toast.error("Select at least one action to authorize, or reject.");
      return;
    }
    if (!comment.trim()) {
      toast.error("A comment is mandatory when authorizing actions.");
      return;
    }
    // absent approved_action_ids = all; send the subset only on partial approval
    onDecide({ decision: "approve", comment, approved_action_ids: allSelected ? undefined : [...selected] });
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2 rounded-md border border-process/40 bg-process-muted/30 p-3 text-sm">
        <ShieldAlert className="mt-0.5 size-4 shrink-0 text-process" />
        <p>
          These actions have real-world side effects (payment release, outbound messages). Authorize only what you intend to execute.
        </p>
      </div>

      <div className="space-y-2">
        {actions.map((a) => (
          <Card key={a.action_id} className={selected.has(a.action_id) ? "border-process/50" : ""}>
            <CardContent className="flex items-start gap-3 p-3">
              <Checkbox checked={selected.has(a.action_id)} onCheckedChange={() => toggle(a.action_id)} className="mt-0.5" aria-label={`Authorize ${a.summary}`} />
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex items-center gap-2">
                  <Badge variant="process" className="font-mono text-[10px]">{a.kind}</Badge>
                  <span className="text-xs text-muted-foreground">{a.action_id}</span>
                </div>
                <p className="text-sm">{a.summary}</p>
                <ArtifactView data={a.detail as Record<string, unknown>} />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {!allSelected && selected.size > 0 && (
        <p className="flex items-center gap-1.5 text-xs text-attention">
          <AlertTriangle className="size-3.5" /> Partial authorization: {selected.size} of {actions.length} actions.
        </p>
      )}

      <CommentField value={comment} onChange={setComment} required />

      <DecisionRow>
        <Button type="button" variant="destructive" onClick={() => guardReject(comment, () => onDecide({ decision: "reject", comment }))} disabled={pending}>
          Reject all
        </Button>
        <Button type="button" variant="success" onClick={approve} disabled={pending}>
          Authorize {allSelected ? "all" : `${selected.size}`}
        </Button>
      </DecisionRow>
    </div>
  );
}

// ---------------- Manual (manual) ----------------

export function ManualVariant({ task, onDecide, pending }: VariantProps) {
  const artifacts = artifactsOf(task);
  const [comment, setComment] = useState("");
  const formId = `manual-${task.task_id}`;
  // A manual gate may or may not produce an editable artifact. With one (e.g. Task_ObtainInfo) the human
  // authors/corrects the output; with none (e.g. Task_ApproveRepair — an input to approve, no output) it is an
  // approve/escalate gate and the "correct it" copy is misleading. Key the copy + primary label off the same
  // editable signal ArtifactEditor uses. (Decision semantics are unchanged — a no-output gate still submits
  // `complete` with no edits, handled by ArtifactEditor.)
  const hasEditable = artifacts.some(isDraft);

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        {hasEditable
          ? "This step is human work. The agent has pre-drafted it — complete or correct it, then complete the task."
          : "This step is human work. Review the drafted output and approve, or escalate."}
      </p>
      <ArtifactEditor
        id={formId}
        artifacts={artifacts}
        isEditable={isDraft}
        agentDrafted={artifacts.some(isAgentDraft)}
        onSubmit={(edits) => onDecide({ decision: "complete", edits, comment })}
      />
      <CommentField value={comment} onChange={setComment} />
      <DecisionRow>
        <Button type="button" variant="destructive" onClick={() => guardReject(comment, () => onDecide({ decision: "escalate", comment }))} disabled={pending}>
          Escalate
        </Button>
        <Button type="submit" form={formId} variant="success" disabled={pending}>
          {hasEditable ? "Complete task" : "Approve"}
        </Button>
      </DecisionRow>
    </div>
  );
}
