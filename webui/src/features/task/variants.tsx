import { useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ArtifactView } from "@/components/artifact/ArtifactView";
import { ArtifactForm } from "@/components/artifact/ArtifactForm";
import { useArtifactSchema } from "@/components/artifact/useArtifactSchema";
import { CommentField, DecisionRow } from "./DecisionKit";
import type { DecideArgs } from "./useTaskActions";
import type { HitlTask, PayloadArtifact, ProposedAction } from "@/api/types";

export interface VariantProps {
  task: HitlTask;
  onDecide: (args: DecideArgs) => void;
  pending: boolean;
}

function primaryArtifact(task: HitlTask): PayloadArtifact | undefined {
  return task.payload.artifacts?.[0] ?? undefined;
}

function guardReject(comment: string, act: () => void) {
  if (!comment.trim()) {
    toast.error("A comment is required to reject.");
    return;
  }
  act();
}

// ---------------- Review (review_after) ----------------

export function ReviewVariant({ task, onDecide, pending }: VariantProps) {
  const art = primaryArtifact(task);
  const { data: schema } = useArtifactSchema(art?.schema);
  const [editing, setEditing] = useState(false);
  const [comment, setComment] = useState("");
  const formId = `edit-${task.task_id}`;

  return (
    <div className="space-y-4">
      {!editing ? (
        <ArtifactView name={art?.name} data={art?.data ?? {}} schemaRef={art?.schema} />
      ) : (
        <ArtifactForm
          id={formId}
          schema={schema}
          defaultData={(art?.data ?? {}) as Record<string, unknown>}
          onSubmit={(edits) => onDecide({ decision: "edit_and_approve", edits, comment })}
        />
      )}

      <CommentField value={comment} onChange={setComment} />

      <DecisionRow>
        {editing ? (
          <>
            <Button variant="ghost" onClick={() => setEditing(false)} disabled={pending}>
              Cancel edit
            </Button>
            <Button type="submit" form={formId} disabled={pending}>
              Save edits & approve
            </Button>
          </>
        ) : (
          <>
            <Button variant="destructive" onClick={() => guardReject(comment, () => onDecide({ decision: "reject", comment }))} disabled={pending}>
              Reject
            </Button>
            <Button variant="outline" onClick={() => setEditing(true)} disabled={pending}>
              Edit & approve
            </Button>
            <Button variant="success" onClick={() => onDecide({ decision: "approve", comment })} disabled={pending}>
              Approve
            </Button>
          </>
        )}
      </DecisionRow>
    </div>
  );
}

// ---------------- Approve result (approve_result) ----------------

export function ApproveResultVariant({ task, onDecide, pending }: VariantProps) {
  const art = primaryArtifact(task);
  const [comment, setComment] = useState("");

  return (
    <div className="space-y-4">
      <ArtifactView name={art?.name} data={art?.data ?? {}} schemaRef={art?.schema} />
      <p className="text-xs text-muted-foreground">This result stands or falls as-is — it cannot be edited here.</p>
      <CommentField value={comment} onChange={setComment} />
      <DecisionRow>
        <Button variant="destructive" onClick={() => guardReject(comment, () => onDecide({ decision: "reject", comment }))} disabled={pending}>
          Reject
        </Button>
        <Button variant="success" onClick={() => onDecide({ decision: "approve", comment })} disabled={pending}>
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
        <Button variant="destructive" onClick={() => guardReject(comment, () => onDecide({ decision: "reject", comment }))} disabled={pending}>
          Reject all
        </Button>
        <Button variant="success" onClick={approve} disabled={pending}>
          Authorize {allSelected ? "all" : `${selected.size}`}
        </Button>
      </DecisionRow>
    </div>
  );
}

// ---------------- Manual (manual) ----------------

export function ManualVariant({ task, onDecide, pending }: VariantProps) {
  const art = primaryArtifact(task);
  const { data: schema } = useArtifactSchema(art?.schema);
  const [comment, setComment] = useState("");
  const formId = `manual-${task.task_id}`;

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">This step is human work. The agent has pre-drafted it — complete or correct it, then complete the task.</p>
      <ArtifactForm
        id={formId}
        schema={schema}
        defaultData={(art?.data ?? {}) as Record<string, unknown>}
        agentDrafted={!!art}
        onSubmit={(edits) => onDecide({ decision: "complete", edits, comment })}
      />
      <CommentField value={comment} onChange={setComment} />
      <DecisionRow>
        <Button variant="destructive" onClick={() => guardReject(comment, () => onDecide({ decision: "escalate", comment }))} disabled={pending}>
          Escalate
        </Button>
        <Button type="submit" form={formId} variant="success" disabled={pending}>
          Complete task
        </Button>
      </DecisionRow>
    </div>
  );
}
