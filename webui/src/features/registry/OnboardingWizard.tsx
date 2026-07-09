import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Check, AlertTriangle, XCircle, Info } from "lucide-react";
import { PageHeader } from "@/app/AppShell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { createPack, uploadBpmn, validatePack, activatePack, type ValidationReport } from "@/api/services/registry";
import { ApiError } from "@/api/client";
import { groupByStage, countBySeverity, SEVERITY_VARIANT } from "@/lib/validation";
import { cn } from "@/lib/utils";

// A skeleton to show the manifest shape — the user replaces this with their real
// pack. It is form input, not rendered backend data.
const EXAMPLE_MANIFEST = JSON.stringify(
  {
    manifest_version: "1.0",
    pack_key: "example-pack",
    version: "0.1.0",
    title: "Example Pack (replace with your manifest)",
    tenant_scope: "global",
    status: "draft",
    process: { bpmn_file: "example-pack.bpmn", process_id: "ExampleProcess", bpmn_sha256: "" },
    triage_rules: [{ rule_id: "example-rule", priority: 100, when: { field: "reason_codes", op: "intersects", value: ["AC01"] } }],
    requires_capabilities: [],
    artifacts: [],
    bindings: [],
  },
  null,
  2,
);

const STEPS = ["Manifest", "BPMN", "Validate", "Activate"] as const;

export function OnboardingWizard() {
  const [step, setStep] = useState(0);
  const [manifestText, setManifestText] = useState(EXAMPLE_MANIFEST);
  const [bpmnText, setBpmnText] = useState("");
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [activated, setActivated] = useState(false);

  const parsedManifest = (() => {
    try {
      return JSON.parse(manifestText);
    } catch {
      return null;
    }
  })();

  const errorCount = report ? countBySeverity(report.findings).error : 0;

  async function runValidation() {
    if (!parsedManifest) {
      toast.error("Manifest is not valid JSON.");
      return;
    }
    setBusy(true);
    try {
      const { pack_key, version } = parsedManifest;
      await createPack(parsedManifest).catch((e) => {
        if (!(e instanceof ApiError) || e.status !== 409) throw e; // ignore "already exists"
      });
      if (bpmnText.trim()) await uploadBpmn(pack_key, version, bpmnText).catch(() => undefined);
      const r = await validatePack(pack_key, version);
      setReport(r);
      setStep(3);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detailText : "Validation failed.");
    } finally {
      setBusy(false);
    }
  }

  async function activate() {
    if (!parsedManifest) return;
    setBusy(true);
    try {
      await activatePack(parsedManifest.pack_key, parsedManifest.version);
      setActivated(true);
      toast.success("Pack activated — version ranges pinned.");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detailText : "Activation failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="mb-4">
        <Link to="/registry" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" /> Registry
        </Link>
      </div>
      <PageHeader title="Onboard process pack" description="Register a manifest, attach BPMN, validate against the 7 stages, then activate." />

      {/* Stepper */}
      <div className="mb-6 flex items-center gap-2">
        {STEPS.map((label, i) => (
          <div key={label} className="flex items-center gap-2">
            <span className={cn("flex size-6 items-center justify-center rounded-full border text-xs", i <= step ? "border-agent bg-agent text-agent-foreground" : "border-border text-muted-foreground")}>
              {i < step ? <Check className="size-3.5" /> : i + 1}
            </span>
            <span className={cn("text-sm", i === step ? "font-medium" : "text-muted-foreground")}>{label}</span>
            {i < STEPS.length - 1 && <span className="mx-1 h-px w-8 bg-border" />}
          </div>
        ))}
      </div>

      {step === 0 && (
        <Card>
          <CardHeader><CardTitle>Manifest JSON</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <Label htmlFor="manifest">Paste or edit the pack manifest</Label>
            <Textarea id="manifest" value={manifestText} onChange={(e) => setManifestText(e.target.value)} rows={16} className="font-mono text-xs" />
            {!parsedManifest && <p className="text-xs text-danger">Invalid JSON.</p>}
            <div className="flex justify-end">
              <Button disabled={!parsedManifest} onClick={() => setStep(1)}>Next: BPMN</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {step === 1 && (
        <Card>
          <CardHeader><CardTitle>BPMN XML</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <Label htmlFor="bpmn">Paste the BPMN process definition (optional in this demo)</Label>
            <Textarea id="bpmn" value={bpmnText} onChange={(e) => setBpmnText(e.target.value)} rows={12} className="font-mono text-xs" placeholder="<bpmn:definitions …>" />
            <div className="flex justify-between">
              <Button variant="ghost" onClick={() => setStep(0)}>Back</Button>
              <Button disabled={busy} onClick={runValidation}>{busy ? "Validating…" : "Validate"}</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {step === 3 && report && (
        <div className="space-y-4">
          <ReportView report={report} />
          <Card>
            <CardHeader><CardTitle>Activate</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {errorCount > 0 ? (
                <div className="flex items-start gap-2 rounded-md border border-danger/40 bg-danger-muted/20 p-3 text-sm">
                  <XCircle className="mt-0.5 size-4 shrink-0 text-danger" />
                  <p>{errorCount} error{errorCount === 1 ? "" : "s"} must be resolved before activation. Fix the manifest/BPMN and re-validate.</p>
                </div>
              ) : activated ? (
                <div className="flex items-start gap-2 rounded-md border border-success/40 bg-success-muted/20 p-3 text-sm">
                  <Check className="mt-0.5 size-4 shrink-0 text-success" />
                  <p>Activated. Every version range was pinned to its highest active version, and triage now routes matching exceptions to this pack.</p>
                </div>
              ) : (
                <>
                  <p className="text-sm text-muted-foreground">
                    Activating pins every capability/artifact range to the highest active version and makes this pack live for triage.
                  </p>
                  <div className="flex justify-end">
                    <Button variant="success" disabled={busy} onClick={activate}>{busy ? "Activating…" : "Activate pack"}</Button>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
          <div className="flex justify-start">
            <Button variant="ghost" onClick={() => { setStep(0); setReport(null); }}>Start over</Button>
          </div>
        </div>
      )}
    </>
  );
}

function ReportView({ report }: { report: ValidationReport }) {
  const counts = countBySeverity(report.findings);
  const groups = groupByStage(report.findings);
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>Validation report</CardTitle>
        <div className="flex gap-1.5">
          <Badge variant="danger">{counts.error} errors</Badge>
          <Badge variant="attention">{counts.warning} warnings</Badge>
          <Badge variant="artifact">{counts.info} info</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {groups.map((g) => (
          <div key={g.stage}>
            <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Stage {g.stage} · {g.name}
            </p>
            <ul className="space-y-1.5">
              {g.findings.map((f, i) => (
                <li key={i} className="flex items-start gap-2 rounded-md border border-border bg-surface/50 p-2.5 text-sm">
                  <SeverityIcon severity={f.severity} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={SEVERITY_VARIANT[f.severity]} className="text-[10px]">{f.code}</Badge>
                      {f.element_id && <span className="font-mono text-xs text-muted-foreground">{f.element_id}</span>}
                    </div>
                    <p className="mt-0.5">{f.message}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function SeverityIcon({ severity }: { severity: string }) {
  if (severity === "error") return <XCircle className="mt-0.5 size-4 shrink-0 text-danger" />;
  if (severity === "warning") return <AlertTriangle className="mt-0.5 size-4 shrink-0 text-attention" />;
  return <Info className="mt-0.5 size-4 shrink-0 text-artifact" />;
}
