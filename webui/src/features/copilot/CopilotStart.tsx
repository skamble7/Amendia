// features/copilot/CopilotStart.tsx — the copilot front door: upload a BPMN, point at the MCP server, paste the
// starting event, and set which events to handle, then Generate. The trigger + triage are USER-PROVIDED (the
// copilot infers the internal design, not the external event contract or business routing).
import { useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { UploadCloud, Wand2, ChevronDown, AlertTriangle } from "lucide-react";
import { PageHeader } from "@/app/AppShell";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { BpmnViewer } from "@/features/registry/BpmnViewer";
import { ApiError } from "@/api/client";
import { generateCopilot, type OnboardingSession } from "@/api/services/registry";
import { TriggerInput, EMPTY_TRIGGER, type TriggerValue } from "./TriggerInput";
import { TriageBuilder, toTriageRules, type TriageRuleDraft } from "./TriageBuilder";

function slugify(s: string): string {
  return s.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

// Read an uploaded file's text. Prefer Blob.text() (browsers); fall back to FileReader (jsdom lacks .text()).
function readText(file: File): Promise<string> {
  if (typeof file.text === "function") return file.text();
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result ?? ""));
    r.onerror = () => reject(r.error);
    r.readAsText(file);
  });
}

/** Turn a generate failure into a plain-language message — a 502 means the model/config isn't reachable. */
function friendlyError(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = err.detail as { error?: string; message?: string } | undefined;
    if (err.status === 502 || detail?.error === "copilot_llm_unavailable") {
      return "The copilot's model isn't reachable right now (its configuration or the model service is down). "
        + "Try again shortly, or ask an administrator to check the copilot model configuration.";
    }
    if (err.isConnectivity) return "Couldn't reach the service. Check your connection and try again.";
    return err.detailText || "The copilot couldn't generate this process. Please review the inputs and try again.";
  }
  return "Something went wrong generating the process. Please try again.";
}

export function CopilotStart({ onGenerated }: { onGenerated: (s: OnboardingSession, bpmnXml: string) => void }) {
  const [xml, setXml] = useState<string>();
  const [fileName, setFileName] = useState<string>();
  const [title, setTitle] = useState("");
  const [packKey, setPackKey] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [version, setVersion] = useState("1.0.0");
  const [domain, setDomain] = useState("");
  const [trigger, setTrigger] = useState<TriggerValue>(EMPTY_TRIGGER);
  const [triage, setTriage] = useState<TriageRuleDraft[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);

  const effectivePackKey = packKey.trim() || slugify(title);
  const triageRules = useMemo(() => toTriageRules(triage, trigger.fields), [triage, trigger.fields]);

  const gen = useMutation({
    mutationFn: () => generateCopilot({
      pack_key: effectivePackKey, version: version.trim() || "1.0.0", title: title.trim(),
      domain: domain.trim() || undefined, bpmn_xml: xml!, bpmn_file: fileName,
      mcp: { endpoint: endpoint.trim() }, trigger: trigger.raw!, triage_rules: triageRules,
    }),
    onSuccess: (s) => onGenerated(s, xml!),
  });

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    setXml(await readText(file));
    if (!title) setTitle(file.name.replace(/\.(bpmn|xml)$/i, "").replace(/[-_]+/g, " "));
  }

  const canGenerate = useMemo(
    () => !!xml && !!endpoint.trim() && !!title.trim() && !!effectivePackKey
      && !!trigger.raw && triageRules.length > 0 && !gen.isPending,
    [xml, endpoint, title, effectivePackKey, trigger.raw, triageRules.length, gen.isPending]);

  if (gen.isPending) {
    return (
      <div className="mx-auto max-w-2xl py-16 text-center">
        <div className="mx-auto mb-6 flex size-14 items-center justify-center rounded-2xl bg-agent-muted text-agent">
          <Wand2 className="size-7 animate-pulse" />
        </div>
        <h2 className="text-xl font-medium">Designing your process…</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          The copilot is reading the diagram, matching each step to your tools, deciding where a person should be
          involved, and checking the whole thing is safe to run. This can take up to a minute.
        </p>
        <ol className="mx-auto mt-6 max-w-sm space-y-1.5 text-left text-sm text-muted-foreground">
          <li>• Reading the diagram &amp; discovering your tools</li>
          <li>• Wiring steps, oversight, and data flow</li>
          <li>• Validating the design</li>
        </ol>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Onboard a process"
        description="Upload your process diagram, point the copilot at your tools, and describe the events it handles. It designs a ready-to-run process you review in plain language."
      />

      {gen.isError && (
        <div className="mb-4 flex items-start gap-2 rounded-md border border-danger/40 bg-danger-muted/20 p-3 text-sm text-danger">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <span>{friendlyError(gen.error)}</span>
        </div>
      )}

      {/* Diagram (left, large) + configuration (right) side by side on wide screens. */}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <Card>
          <CardContent className="pt-5">
            <Label className="mb-1.5 block text-sm font-medium">Process diagram (BPMN)</Label>
            <input ref={fileInput} type="file" accept=".bpmn,.xml,application/xml,text/xml"
              className="hidden" onChange={onFile} aria-label="BPMN file" />
            <div className="flex items-center gap-3">
              <Button variant="outline" onClick={() => fileInput.current?.click()}>
                <UploadCloud className="size-4" /> {fileName ? "Choose a different file" : "Upload a .bpmn file"}
              </Button>
              {fileName && <span className="text-sm text-muted-foreground">{fileName}</span>}
            </div>
            {xml
              ? <div className="mt-3 h-[28rem] overflow-hidden rounded-md border border-border"><BpmnViewer xml={xml} className="h-full" controls /></div>
              : <div className="mt-3 flex h-[28rem] items-center justify-center rounded-md border border-dashed border-border text-sm text-muted-foreground">Your diagram preview appears here</div>}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardContent className="grid gap-4 pt-5">
              <div>
                <Label htmlFor="mcp" className="mb-1.5 block text-sm font-medium">Your tools (MCP server address)</Label>
                <Input id="mcp" value={endpoint} onChange={(e) => setEndpoint(e.target.value)} placeholder="https://your-mcp-server/mcp" />
                <p className="mt-1 text-xs text-muted-foreground">The copilot connects here to discover the actions your process can perform.</p>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <Label htmlFor="title" className="mb-1.5 block text-sm font-medium">Process name</Label>
                  <Input id="title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Customer onboarding" />
                </div>
                <div>
                  <Label htmlFor="pk" className="mb-1.5 block text-sm font-medium">Identifier</Label>
                  <Input id="pk" value={effectivePackKey} onChange={(e) => setPackKey(e.target.value)} placeholder="customer-onboarding" className="font-mono text-sm" />
                </div>
              </div>
              <div>
                <button type="button" onClick={() => setAdvanced((v) => !v)}
                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
                  <ChevronDown className={`size-3.5 transition-transform ${advanced ? "rotate-180" : ""}`} /> Advanced
                </button>
                {advanced && (
                  <div className="mt-3 grid gap-4 sm:grid-cols-2">
                    <div>
                      <Label htmlFor="ver" className="mb-1.5 block text-sm font-medium">Version</Label>
                      <Input id="ver" value={version} onChange={(e) => setVersion(e.target.value)} className="font-mono text-sm" />
                    </div>
                    <div>
                      <Label htmlFor="dom" className="mb-1.5 block text-sm font-medium">Domain (optional)</Label>
                      <Input id="dom" value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="derived from the identifier" className="font-mono text-sm" />
                    </div>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          <Card><CardContent className="pt-5"><TriggerInput value={trigger} onChange={setTrigger} /></CardContent></Card>
          <Card><CardContent className="pt-5"><TriageBuilder fields={trigger.fields} rules={triage} onChange={setTriage} /></CardContent></Card>
        </div>
      </div>

      <div className="mt-4 flex items-center justify-end gap-3">
        {!canGenerate && !gen.isPending && (
          <span className="text-xs text-muted-foreground">Upload a diagram, add your tools, the starting event, and at least one routing rule.</span>
        )}
        <Button onClick={() => gen.mutate()} disabled={!canGenerate}>
          <Wand2 className="size-4" /> Generate process
        </Button>
      </div>
    </div>
  );
}
