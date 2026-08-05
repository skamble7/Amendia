import { GitCompareArrows, ShieldCheck } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ArtifactView } from "@/components/artifact/ArtifactView";
import { formatDateTime } from "@/lib/format";
import type { DecisionTrailOut } from "@/api/types";

interface Props {
  trail: DecisionTrailOut | null | undefined;
  /** agent-runtime InstanceState.artifacts, keyed by artifact NAME (values; debug-API gated). */
  artifacts?: Record<string, unknown>;
  /** artifact_key -> artifact name, to resolve a glea ref to a concrete value. */
  artifactKeyToName: Map<string, string>;
}

/**
 * The proposed → approved decision trail (ADR-058 §2). glea supplies the gate metadata + artifact
 * REFERENCES; agent-runtime supplies the concrete VALUES (rendered through ArtifactView, which applies
 * the repair-correction renderer / CorrectionDiff where the artifact carries corrections). Degrades to
 * a note when glea is unreachable, and to reference-only when the runtime debug API is off.
 */
export function DecisionTrail({ trail, artifacts, artifactKeyToName }: Props) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2">
          <GitCompareArrows className="size-4" /> Decision trail
        </CardTitle>
        {trail ? <span className="text-xs text-muted-foreground">{trail.count} gates</span> : null}
      </CardHeader>
      <CardContent className="space-y-3">
        {!trail ? (
          <p className="text-sm text-muted-foreground">Decision trail unavailable (glea-service not reachable).</p>
        ) : trail.gates.length === 0 ? (
          <p className="text-sm text-muted-foreground">No gate decisions recorded for this instance.</p>
        ) : (
          trail.gates.map((g, i) => {
            const approvedName = g.approved ? artifactKeyToName.get(g.approved.artifact_key) : undefined;
            const proposedName = g.proposed ? artifactKeyToName.get(g.proposed.artifact_key) : undefined;
            const approvedVal = approvedName ? artifacts?.[approvedName] : undefined;
            const proposedVal = proposedName ? artifacts?.[proposedName] : undefined;
            const differ =
              !!g.proposed && !!g.approved && g.proposed.artifact_key !== g.approved.artifact_key;
            return (
              <div key={i} className="rounded-md border border-border p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">{g.element_id}</span>
                  <Badge variant={g.decision === "reject" ? "danger" : "success"}>{g.decision}</Badge>
                  {g.sod_satisfied ? (
                    <Badge variant="success">
                      <ShieldCheck className="size-3" /> Four-eyes
                    </Badge>
                  ) : null}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {g.decided_by || "—"}
                  {g.role ? ` · ${g.role}` : ""}
                  {g.decided_at ? ` · ${formatDateTime(g.decided_at)}` : ""}
                </p>
                {g.comment ? (
                  <p className="mt-1 text-sm italic text-muted-foreground">“{g.comment}”</p>
                ) : null}

                {differ && proposedVal !== undefined && approvedVal !== undefined ? (
                  <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-2">
                    <div>
                      <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Proposed</p>
                      <ArtifactView data={proposedVal as Record<string, unknown>} schemaRef={g.proposed?.schema_ref} />
                    </div>
                    <div>
                      <p className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">Approved</p>
                      <ArtifactView data={approvedVal as Record<string, unknown>} schemaRef={g.approved?.schema_ref} />
                    </div>
                  </div>
                ) : approvedVal !== undefined ? (
                  <div className="mt-2">
                    <ArtifactView data={approvedVal as Record<string, unknown>} schemaRef={g.approved?.schema_ref} />
                  </div>
                ) : g.approved ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Output <Badge variant="artifact">{g.approved.artifact_key}</Badge> — values need the runtime
                    debug API.
                  </p>
                ) : null}
              </div>
            );
          })
        )}
      </CardContent>
    </Card>
  );
}
