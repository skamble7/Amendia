// CopilotCapabilitiesStep — ADR-054/copilot. The MCP server was already connected + introspected at Generate, so
// the copilot's Capabilities step is READ-MOSTLY: it shows the connected endpoint and the discovered capabilities
// (with side-effect flags) instead of asking for the URL a second time. Re-introspect / edit is an OPTIONAL action
// that reveals the full (manual-wizard) CapabilitiesStep, seeded with the known endpoint.
import { useState } from "react";
import { Boxes, Pencil, ShieldAlert } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { CapabilitiesStep } from "@/features/registry/OnboardingWizard";
import { type OnboardingSession } from "@/api/services/registry";

export function CopilotCapabilitiesStep({ session, onDone }: {
  session: OnboardingSession;
  onDone: (s: OnboardingSession) => void;
}) {
  const [editing, setEditing] = useState(false);
  const caps = session.staged_capabilities ?? [];
  const endpoint = caps.find((c) => c.endpoint)?.endpoint ?? "";

  if (editing) {
    // full editable step, seeded with the already-known endpoint (no second URL entry)
    return <CapabilitiesStep session={session} prefilledEndpoint={endpoint} onDone={(s) => { setEditing(false); onDone(s); }} />;
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle className="text-sm">Connected tool server</CardTitle></CardHeader>
        <CardContent className="flex items-center justify-between gap-3">
          <p className="min-w-0 truncate font-mono text-sm">{endpoint || "—"}</p>
          <Badge variant="outline" className="whitespace-nowrap">connected at generate</Badge>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle className="text-sm">Discovered capabilities</CardTitle>
          <Button variant="outline" size="sm" className="gap-1" onClick={() => setEditing(true)}>
            <Pencil className="size-3.5" /> Re-introspect / edit
          </Button>
        </CardHeader>
        <CardContent className="space-y-2">
          {caps.length === 0 ? (
            <p className="text-sm text-muted-foreground">No capabilities were staged.</p>
          ) : (
            caps.map((c) => (
              <div key={c.capability_id} className="flex items-center gap-2 rounded-md border border-border p-2">
                <Boxes className="size-4 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate text-sm">{c.tool ?? c.capability_id}</span>
                {c.side_effect === "side_effectful" && (
                  <Badge variant="outline" className="gap-1"><ShieldAlert className="size-3" /> real-world effect</Badge>
                )}
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}
