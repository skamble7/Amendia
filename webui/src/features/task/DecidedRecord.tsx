import { CheckCircle2, XCircle, Lock } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ArtifactView } from "@/components/artifact/ArtifactView";
import { DECISION_META } from "@/lib/hitl";
import { formatDateTime } from "@/lib/format";
import type { HitlTask, PayloadArtifact } from "@/api/types";

/** Immutable record view for a decided task. */
export function DecidedRecord({ task }: { task: HitlTask }) {
  const d = task.decision;
  if (!d) return null;
  const meta = DECISION_META[d.decision as keyof typeof DECISION_META];
  const positive = meta?.tone === "success";
  const art = task.payload.artifacts?.[0] as PayloadArtifact | undefined;
  const hasEdits = d.edits && Object.keys(d.edits).length > 0;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex-row items-center gap-2">
          <Lock className="size-4 text-muted-foreground" />
          <CardTitle>Decision record</CardTitle>
          <Badge variant="outline" className="ml-auto text-[10px]">Immutable</Badge>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-2">
            {positive ? <CheckCircle2 className="size-5 text-success" /> : <XCircle className="size-5 text-danger" />}
            <span className="text-lg font-medium">{meta?.label ?? d.decision}</span>
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Decided by</dt>
            <dd className="text-right">{d.decided_by}</dd>
            <dt className="text-muted-foreground">When</dt>
            <dd className="text-right">{formatDateTime(d.decided_at)}</dd>
            {d.approved_action_ids && (
              <>
                <dt className="text-muted-foreground">Authorized actions</dt>
                <dd className="text-right">{d.approved_action_ids.join(", ")}</dd>
              </>
            )}
          </dl>
          {d.comment && (
            <div className="rounded-md border border-border bg-surface/60 p-3 text-sm">
              <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">Comment</p>
              {d.comment}
            </div>
          )}
        </CardContent>
      </Card>

      {hasEdits ? (
        <Card>
          <CardHeader>
            <CardTitle>Submitted edits</CardTitle>
          </CardHeader>
          <CardContent>
            <ArtifactView name={art?.name} data={d.edits as Record<string, unknown>} schemaRef={art?.schema} />
          </CardContent>
        </Card>
      ) : art ? (
        <Card>
          <CardHeader>
            <CardTitle>Reviewed artifact</CardTitle>
          </CardHeader>
          <CardContent>
            <ArtifactView name={art.name} data={art.data as Record<string, unknown>} schemaRef={art.schema} />
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
