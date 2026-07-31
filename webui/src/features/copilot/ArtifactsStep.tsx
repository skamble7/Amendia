// ArtifactsStep — ADR-054 Part B. The "Artifacts & schemas" review step: tool inputs/outputs are fixed by the
// connected tools (shown read-only); every HUMAN-authored artifact (a human task's output) gets a schema refiner
// with a live ArtifactForm preview, so the operator turns a loose derived schema into clean, labeled, typed fields
// that drive the real HITL form. Saving persists via the bump-aware refine endpoint (Part C).
import { useState } from "react";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ArtifactForm } from "@/components/artifact/ArtifactForm";
import { humanizeKey, type JsonSchema } from "@/components/artifact/schema";
import { ApiError } from "@/api/client";
import {
  refineOnboardingArtifact, type OnboardingSession, type OnbStagedArtifact,
} from "@/api/services/registry";
import { SchemaRefiner } from "./SchemaRefiner";

export function ArtifactsStep({ session, onSession }: {
  session: OnboardingSession;
  onSession: (s: OnboardingSession) => void;
}) {
  const human = session.authored_artifacts ?? [];
  const toolIO = session.staged_artifacts ?? [];
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        The artifacts that flow through your process. Tool inputs and outputs are fixed by the connected tools; refine
        each human-authored artifact so the person who fills it sees clean, labeled fields — not a raw JSON blob.
      </p>
      {human.length === 0 ? (
        <p className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
          No human-authored artifacts — every artifact here is a tool input or output.
        </p>
      ) : (
        human.map((a) => <HumanArtifactRefiner key={a.artifact_key} session={session} artifact={a} onSession={onSession} />)
      )}
      {toolIO.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-sm">Tool inputs &amp; outputs (fixed)</CardTitle></CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {toolIO.map((a) => <Badge key={a.artifact_key} variant="outline" className="font-mono text-xs">{a.artifact_key}</Badge>)}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function HumanArtifactRefiner({ session, artifact, onSession }: {
  session: OnboardingSession;
  artifact: OnbStagedArtifact;
  onSession: (s: OnboardingSession) => void;
}) {
  const [schema, setSchema] = useState<JsonSchema>(artifact.json_schema as JsonSchema);
  const [title, setTitle] = useState(artifact.title);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      const s = await refineOnboardingArtifact(session.session_id, {
        artifact_key: artifact.artifact_key, json_schema: schema, title,
      });
      onSession(s);
      toast.success(`Refined ${humanizeKey(artifact.artifact_key)}`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detailText : "Could not save the schema.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          Human-authored: <span className="font-mono text-xs">{artifact.artifact_key}</span>
          <Badge variant="outline">{artifact.version}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-6 md:grid-cols-2">
        <div className="space-y-3">
          <label className="block text-xs font-medium text-muted-foreground">
            Title
            <Input value={title} onChange={(e) => setTitle(e.target.value)} className="mt-1 h-8" />
          </label>
          <SchemaRefiner schema={artifact.json_schema as JsonSchema} onChange={setSchema} />
        </div>
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">Live form preview</p>
          <div className="rounded-md border border-border p-3">
            <ArtifactForm id={`preview-${artifact.artifact_key}`} schema={schema} defaultData={{}} onSubmit={() => {}} />
          </div>
        </div>
      </CardContent>
      <CardContent className="flex justify-end border-t border-border pt-3">
        <Button size="sm" disabled={busy} onClick={save}>
          {busy ? <><Loader2 className="mr-1 size-4 animate-spin" /> Saving…</> : "Save schema"}
        </Button>
      </CardContent>
    </Card>
  );
}
