import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import {
  ArrowLeft, ArrowRight, Check, AlertTriangle, XCircle, Info, Loader2, Search,
  Plus, Trash2, ShieldAlert, Boxes, Eye, Upload, FileCode,
} from "lucide-react";
import { PageHeader } from "@/app/AppShell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { BpmnViewer } from "./BpmnViewer";
import { ApiError } from "@/api/client";
import { groupByStage, countBySeverity, SEVERITY_VARIANT } from "@/lib/validation";
import { cn } from "@/lib/utils";
import {
  assembleOnboarding, attachOnboardingBpmn, commitOnboarding, createOnboardingSession,
  getOnboardingSession, introspectMcp, setOnboardingBindings, setOnboardingCapabilities,
  setOnboardingPolicies, setOnboardingTriage,
  type BindingInput, type CapabilityToolSelection, type IntrospectedTool, type OnbTriageRule,
  type OnboardingSession, type OnboardingState, type ValidationReport,
} from "@/api/services/registry";
import { useCapabilities, useOnboardingSessions } from "./queries";

const selectCls =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50";

const HITL_MODES = ["none", "review_after", "approve_result", "approve_actions", "manual"] as const;
const HITL_RANK: Record<string, number> = { none: 0, review_after: 1, approve_result: 1, approve_actions: 2, manual: 2 };

const STEPS = [
  "Basics", "BPMN", "Capabilities", "Bindings", "Triage", "Policies", "Review & activate",
] as const;
const STATE_STEP: Record<OnboardingState, number> = {
  initiated: 0, bpmn_attached: 1, capabilities_resolved: 2, bindings_set: 3,
  triage_set: 4, policies_set: 5, assembled: 6, completed: 6,
};

// -- error helpers ------------------------------------------------------------
type FieldError = { field?: string; element_id?: string; allowed_min_mode?: string; message: string };
function extractErrors(err: unknown): { general: string; fields: FieldError[]; findings: any[] } {
  if (!(err instanceof ApiError)) return { general: "Unexpected error.", fields: [], findings: [] };
  const d = err.detail as any;
  if (typeof d === "string") return { general: d, fields: [], findings: [] };
  const fields: FieldError[] = Array.isArray(d?.errors)
    ? d.errors.map((e: any) => ({
        field: e.field ?? e.tool ?? e.ref ?? e.rule_id,
        element_id: e.element_id, allowed_min_mode: e.allowed_min_mode, message: e.message,
      }))
    : [];
  return { general: d?.message ?? (fields.length ? "" : err.detailText), fields, findings: d?.findings ?? [] };
}

export function OnboardingWizard() {
  const { sessionId } = useParams();
  if (!sessionId) return <StartScreen />;
  return <SessionWizard sessionId={sessionId} />;
}

// ---------------------------------------------------------------------------
// Start screen: resume an in-progress session, or open a new one.
// ---------------------------------------------------------------------------
function StartScreen() {
  const navigate = useNavigate();
  const { data: sessions } = useOnboardingSessions();
  const [form, setForm] = useState({ pack_key: "", version: "1.0.0", title: "", description: "", default_domain: "payment" });
  const [errs, setErrs] = useState<FieldError[]>([]);
  const [busy, setBusy] = useState(false);
  const inProgress = (sessions ?? []).filter((s) => s.state !== "completed");

  async function create() {
    setBusy(true);
    setErrs([]);
    try {
      const s = await createOnboardingSession(form);
      navigate(`/registry/onboard/${s.session_id}`);
    } catch (e) {
      const { general, fields } = extractErrors(e);
      setErrs(fields);
      if (general) toast.error(general);
    } finally {
      setBusy(false);
    }
  }

  const err = (f: string) => errs.find((e) => e.field === f)?.message;

  return (
    <>
      <BackLink />
      <PageHeader title="Onboard process pack" description="Author a pack through forms — the backend owns ordering, staging, validation and the commit chain." />

      {inProgress.length > 0 && (
        <Card className="mb-5">
          <CardHeader><CardTitle>Resume onboarding</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {inProgress.map((s) => (
              <Link key={s.session_id} to={`/registry/onboard/${s.session_id}`}
                className="flex items-center gap-3 rounded-md border border-border p-3 hover:bg-surface/60">
                <Boxes className="size-4 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{s.basics.pack_key}@{s.basics.version}</p>
                  <p className="truncate text-xs text-muted-foreground">{s.basics.title} · step {STATE_STEP[s.state] + 1} of 7</p>
                </div>
                <Badge variant="outline">{s.state.replace(/_/g, " ")}</Badge>
                <ArrowRight className="size-4 text-muted-foreground" />
              </Link>
            ))}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle>New pack</CardTitle></CardHeader>
        <CardContent className="grid max-w-2xl grid-cols-2 gap-4">
          <Field label="Pack key" hint="kebab-case" error={err("pack_key")}>
            <Input value={form.pack_key} onChange={(e) => setForm({ ...form, pack_key: e.target.value })} placeholder="wire-repair-standard" />
          </Field>
          <Field label="Version" hint="semver" error={err("version")}>
            <Input value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value })} placeholder="1.0.0" />
          </Field>
          <Field label="Title" className="col-span-2" error={err("title")}>
            <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Wire repair — standard" />
          </Field>
          <Field label="Description" className="col-span-2">
            <Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </Field>
          <Field label="Default domain" hint="seeds suggested ids, e.g. cap.<domain>.<tool>" error={err("default_domain")}>
            <Input value={form.default_domain} onChange={(e) => setForm({ ...form, default_domain: e.target.value })} />
          </Field>
          <div className="col-span-2 flex justify-end">
            <Button disabled={busy} onClick={create}>{busy ? <><Loader2 className="mr-1 size-4 animate-spin" /> Creating…</> : "Create & continue"}</Button>
          </div>
        </CardContent>
      </Card>
    </>
  );
}

// ---------------------------------------------------------------------------
// The session wizard — thin renderer of backend session state.
// ---------------------------------------------------------------------------
function SessionWizard({ sessionId }: { sessionId: string }) {
  const [session, setSession] = useState<OnboardingSession | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [step, setStep] = useState(0);

  useEffect(() => {
    let live = true;
    getOnboardingSession(sessionId)
      .then((s) => { if (live) { setSession(s); setStep(STATE_STEP[s.state]); } })
      .catch((e) => setLoadError(e instanceof ApiError ? e.detailText : "Could not load session."));
    return () => { live = false; };
  }, [sessionId]);

  if (loadError) return <><BackLink /><EmptyBox title="Session unavailable" body={loadError} /></>;
  if (!session) return <><BackLink /><EmptyBox title="Loading…" body="" /></>;

  const reached = STATE_STEP[session.state];
  const apply = (s: OnboardingSession, nextStep?: number) => {
    setSession(s);
    if (s.last_cleared.length) toast.info(`Reset downstream: ${s.last_cleared.join(", ").replace(/_/g, " ")}`);
    if (nextStep !== undefined) setStep(nextStep);
    else setStep(STATE_STEP[s.state]);
  };

  return (
    <>
      <BackLink />
      <PageHeader
        title={`Onboard · ${session.basics.pack_key}@${session.basics.version}`}
        description={session.basics.title}
      />

      {/* Stepper */}
      <div className="mb-6 flex flex-wrap items-center gap-y-2">
        {STEPS.map((label, i) => {
          const done = i < reached || session.state === "completed";
          const isReachable = i <= reached;
          return (
            <div key={label} className="flex items-center">
              <button
                disabled={!isReachable}
                onClick={() => isReachable && setStep(i)}
                className={cn("flex items-center gap-2", !isReachable && "cursor-not-allowed opacity-50")}
              >
                <span className={cn(
                  "flex size-6 items-center justify-center rounded-full border text-xs",
                  i === step ? "border-agent bg-agent text-agent-foreground"
                    : done ? "border-success bg-success text-success-foreground"
                    : "border-border text-muted-foreground",
                )}>
                  {done && i !== step ? <Check className="size-3.5" /> : i + 1}
                </span>
                <span className={cn("text-sm", i === step ? "font-medium" : "text-muted-foreground")}>{label}</span>
              </button>
              {i < STEPS.length - 1 && <span className="mx-2 h-px w-6 bg-border" />}
            </div>
          );
        })}
      </div>

      {step === 0 && <BasicsStep session={session} onNext={() => setStep(1)} />}
      {step === 1 && <BpmnStep session={session} onDone={(s) => apply(s, 2)} />}
      {step === 2 && <CapabilitiesStep session={session} onDone={(s) => apply(s, 3)} />}
      {step === 3 && <BindingsStep session={session} onDone={(s) => apply(s, 4)} />}
      {step === 4 && <TriageStep session={session} onDone={(s) => apply(s, 5)} />}
      {step === 5 && <PoliciesStep session={session} onDone={(s) => apply(s, 6)} />}
      {step === 6 && <ReviewStep session={session} onChange={(s) => setSession(s)} goStep={setStep} />}
    </>
  );
}

// -- Step 1: basics (read-only once created; the backend has no basics-edit) --
function BasicsStep({ session, onNext }: { session: OnboardingSession; onNext: () => void }) {
  const b = session.basics;
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle>Pack basics</CardTitle></CardHeader>
        <CardContent className="grid max-w-2xl grid-cols-2 gap-4 text-sm">
          <ReadRow label="Pack key" value={b.pack_key} mono />
          <ReadRow label="Version" value={b.version} mono />
          <ReadRow label="Title" value={b.title} />
          <ReadRow label="Default domain" value={b.default_domain} mono />
          {b.description && <ReadRow label="Description" value={b.description} className="col-span-2" />}
          <p className="col-span-2 text-xs text-muted-foreground">Basics are fixed for a session. To change the key or version, start a new onboarding.</p>
        </CardContent>
      </Card>
      <StepFooter summary="session created — basics saved" busy={false} onNext={onNext} nextLabel="Continue to BPMN" />
    </div>
  );
}

// -- Step 2: BPMN --------------------------------------------------------------
function BpmnStep({ session, onDone }: { session: OnboardingSession; onDone: (s: OnboardingSession) => void }) {
  const [xml, setXml] = useState("");
  const [fileName, setFileName] = useState("");
  const [busy, setBusy] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [findings, setFindings] = useState<any[]>([]);
  const [general, setGeneral] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  async function loadFile(file: File | undefined | null) {
    if (!file) return;
    const text = await file.text();
    setXml(text); setFileName(file.name); setFindings([]); setGeneral("");
  }

  async function submit() {
    setBusy(true); setFindings([]); setGeneral("");
    try {
      onDone(await attachOnboardingBpmn(session.session_id, { bpmn_xml: xml, bpmn_file: fileName || undefined }));
    } catch (e) {
      const x = extractErrors(e);
      setFindings(x.findings); setGeneral(x.general);
      if (!x.findings.length && x.general) toast.error(x.general);
    } finally { setBusy(false); }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>BPMN process definition</CardTitle>
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="outline" size="sm" disabled={!xml.trim()}><Eye className="mr-1 size-4" /> View diagram</Button>
            </DialogTrigger>
            <DialogContent className="max-w-4xl">
              <DialogHeader><DialogTitle>Process diagram {fileName && <span className="font-mono text-xs font-normal text-muted-foreground">· {fileName}</span>}</DialogTitle></DialogHeader>
              <BpmnViewer xml={xml} className="h-[70vh]" />
            </DialogContent>
          </Dialog>
        </CardHeader>
        <CardContent className="space-y-3">
          <Label>Upload or paste a BPMN 2.0 XML. The server parses it and returns the task &amp; gateway inventory (exclusive gateways only).</Label>

          {/* Upload zone (drag-drop + file picker) */}
          <input
            ref={inputRef} type="file" accept=".bpmn,.xml,text/xml,application/xml" className="hidden"
            onChange={(e) => { loadFile(e.target.files?.[0]); e.target.value = ""; }}
          />
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); loadFile(e.dataTransfer.files?.[0]); }}
            className={cn(
              "flex flex-col items-center gap-2 rounded-md border border-dashed p-6 text-center transition-colors",
              dragOver ? "border-agent bg-agent/5" : "border-border bg-surface/40",
            )}
          >
            {fileName ? (
              <div className="flex items-center gap-2 text-sm">
                <FileCode className="size-4 text-agent" />
                <span className="font-mono text-xs">{fileName}</span>
                <Button variant="ghost" size="sm" onClick={() => inputRef.current?.click()}>Replace</Button>
              </div>
            ) : (
              <>
                <Upload className="size-6 text-muted-foreground" />
                <div className="text-sm font-medium">Drag &amp; drop a .bpmn file</div>
                <div className="text-xs text-muted-foreground">or use the picker · BPMN 2.0, exclusive gateways only</div>
                <Button variant="secondary" size="sm" className="mt-1" onClick={() => inputRef.current?.click()}>
                  <Upload className="mr-1 size-4" /> Choose file
                </Button>
              </>
            )}
          </div>

          <Textarea
            id="bpmn" value={xml}
            onChange={(e) => { setXml(e.target.value); setFileName(""); }}
            rows={12} className="font-mono text-xs" placeholder="…or paste <bpmn:definitions …> here"
          />
          {general && <p className="text-sm text-danger">{general}</p>}
          {findings.length > 0 && (
            <div className="rounded-md border border-danger/40 bg-danger-muted/20 p-3">
              <p className="mb-1 text-sm font-medium text-danger">BPMN rejected</p>
              <ul className="space-y-1 text-sm">
                {findings.map((f, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <XCircle className="mt-0.5 size-3.5 shrink-0 text-danger" />
                    <span><span className="font-mono text-xs">{f.code}</span>{f.element_id ? ` · ${f.element_id}` : ""} — {f.message}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="flex justify-end">
            <Button disabled={busy || !xml.trim()} onClick={submit}>{busy ? <><Loader2 className="mr-1 size-4 animate-spin" /> Parsing…</> : "Parse & continue"}</Button>
          </div>
        </CardContent>
      </Card>
      {session.bpmn && <InventoryCard session={session} />}
    </div>
  );
}

function InventoryCard({ session }: { session: OnboardingSession }) {
  const b = session.bpmn!;
  const group = (label: string, ids: string[], variant: any) => (
    <div>
      <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">{label} · {ids.length}</p>
      <div className="flex flex-wrap gap-1.5">
        {ids.map((id) => <Badge key={id} variant={variant} className="font-mono text-[11px]">{id}</Badge>)}
        {ids.length === 0 && <span className="text-xs text-muted-foreground">none</span>}
      </div>
    </div>
  );
  return (
    <Card>
      <CardHeader><CardTitle>Current inventory · {b.process_id}</CardTitle></CardHeader>
      <CardContent className="grid grid-cols-3 gap-4">
        {group("Service tasks", b.service_tasks, "agent")}
        {group("User tasks", b.user_tasks, "attention")}
        {group("Gateways", b.gateways, "process")}
      </CardContent>
    </Card>
  );
}

// -- Step 3: capabilities (MCP introspection + reuse) --------------------------
interface ToolDraft extends IntrospectedTool {
  selected: boolean;
  input_artifact_key: string; output_artifact_key: string; capability_id: string;
  side_effect: string; idempotent: boolean;
}
function CapabilitiesStep({ session, onDone }: { session: OnboardingSession; onDone: (s: OnboardingSession) => void }) {
  const [endpoint, setEndpoint] = useState("");
  const [transport, setTransport] = useState("streamable_http");
  const [introspecting, setIntrospecting] = useState(false);
  const [drafts, setDrafts] = useState<ToolDraft[]>([]);
  const [reused, setReused] = useState<string[]>(session.reused_capability_refs);
  const [busy, setBusy] = useState(false);
  const { data: catalog } = useCapabilities();

  async function introspect() {
    setIntrospecting(true);
    try {
      const res = await introspectMcp({ endpoint, transport, domain: session.basics.default_domain });
      setDrafts(res.tools.map((t) => ({
        ...t, selected: false,
        input_artifact_key: t.suggested_input_artifact_key ?? "",
        output_artifact_key: t.suggested_output_artifact_key ?? "",
        capability_id: t.suggested_capability_id ?? "",
        side_effect: "read_only", idempotent: true,
      })));
    } catch (e) {
      toast.error(extractErrors(e).general || "Introspection failed.");
    } finally { setIntrospecting(false); }
  }

  async function submit() {
    setBusy(true);
    try {
      const tools: CapabilityToolSelection[] = drafts.filter((d) => d.selected && d.compliance.compliant).map((d) => ({
        tool: d.name, endpoint, transport, domain: session.basics.default_domain,
        input_artifact_key: d.input_artifact_key, output_artifact_key: d.output_artifact_key,
        capability_id: d.capability_id, side_effect: d.side_effect, idempotent: d.idempotent,
        input_schema: d.input_schema ?? undefined, output_schema: d.output_schema ?? undefined,
      }));
      onDone(await setOnboardingCapabilities(session.session_id, { tools, reused_capability_refs: reused }));
    } catch (e) {
      const x = extractErrors(e);
      toast.error(x.fields.map((f) => `${f.field}: ${f.message}`).join("; ") || x.general);
    } finally { setBusy(false); }
  }

  const patch = (name: string, p: Partial<ToolDraft>) => setDrafts((ds) => ds.map((d) => d.name === name ? { ...d, ...p } : d));
  const stagedCount = drafts.filter((d) => d.selected && d.compliance.compliant).length;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle>Create capabilities from an MCP server</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">Point at a running MCP server. Each compliant tool becomes an input artifact, an output artifact, and one <span className="font-mono">mcp</span> capability. Capability creation here is MCP-only; other kinds are reuse-only.</p>
          <div className="flex items-end gap-2">
            <div className="flex-1"><Label>MCP server URL</Label><Input value={endpoint} onChange={(e) => setEndpoint(e.target.value)} placeholder="https://mcp.internal/payments" /></div>
            <select className={cn(selectCls, "w-40")} value={transport} onChange={(e) => setTransport(e.target.value)}>
              <option value="streamable_http">streamable_http</option>
              <option value="sse">sse</option>
            </select>
            <Button disabled={introspecting || !endpoint.trim()} onClick={introspect}>
              {introspecting ? <Loader2 className="mr-1 size-4 animate-spin" /> : <Search className="mr-1 size-4" />} Introspect
            </Button>
          </div>

          {drafts.map((d) => (
            <div key={d.name} className={cn("rounded-md border p-3", d.selected ? "border-agent" : "border-border")}>
              <div className="flex items-start gap-3">
                <input type="checkbox" disabled={!d.compliance.compliant} checked={d.selected}
                  onChange={(e) => patch(d.name, { selected: e.target.checked })} className="mt-1" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-medium">{d.name}</span>
                    {d.compliance.compliant
                      ? <Badge variant="success" className="text-[10px]">compliant</Badge>
                      : <Badge variant="attention" className="text-[10px]">flagged</Badge>}
                  </div>
                  {d.description && <p className="mt-0.5 text-sm text-muted-foreground">{d.description}</p>}
                  {!d.compliance.compliant && (
                    <p className="mt-1 text-xs text-attention">
                      {d.compliance.reasons.join("; ")} · see the MCP Implementor Guideline.
                    </p>
                  )}
                  {d.selected && d.compliance.compliant && (
                    <div className="mt-3 grid grid-cols-2 gap-3 border-t border-border pt-3">
                      <Field label="Input artifact" hint="suggested"><Input value={d.input_artifact_key} onChange={(e) => patch(d.name, { input_artifact_key: e.target.value })} className="font-mono text-xs" /></Field>
                      <Field label="Output artifact" hint="suggested"><Input value={d.output_artifact_key} onChange={(e) => patch(d.name, { output_artifact_key: e.target.value })} className="font-mono text-xs" /></Field>
                      <Field label="Capability id" hint="suggested" className="col-span-2"><Input value={d.capability_id} onChange={(e) => patch(d.name, { capability_id: e.target.value })} className="font-mono text-xs" /></Field>
                      <Field label="Side effect">
                        <select className={selectCls} value={d.side_effect} onChange={(e) => patch(d.name, { side_effect: e.target.value })}>
                          <option value="read_only">read_only</option>
                          <option value="side_effectful">side_effectful</option>
                        </select>
                        {d.side_effect === "side_effectful" && <p className="mt-1 flex items-center gap-1 text-xs text-process"><ShieldAlert className="size-3" /> needs an Authorize-actions gate downstream</p>}
                      </Field>
                      <Field label="Idempotent">
                        <select className={selectCls} value={String(d.idempotent)} onChange={(e) => patch(d.name, { idempotent: e.target.value === "true" })}>
                          <option value="true">yes</option>
                          <option value="false">no</option>
                        </select>
                      </Field>
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Reuse existing capabilities</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {(catalog ?? []).map((c: any) => {
            const ref = `${c.capability_id}@^${c.version}`;
            const on = reused.includes(ref);
            return (
              <button key={ref} onClick={() => setReused((r) => on ? r.filter((x) => x !== ref) : [...r, ref])}
                className={cn("flex w-full items-center gap-3 rounded-md border p-2.5 text-left", on ? "border-agent" : "border-border")}>
                <input type="checkbox" readOnly checked={on} />
                <span className="flex-1 font-mono text-xs">{ref}</span>
                <Badge variant="outline" className="text-[10px]">{c.kind}</Badge>
                <Badge variant={c.side_effect === "side_effectful" ? "process" : "artifact"} className="text-[10px]">{c.side_effect}</Badge>
              </button>
            );
          })}
          {(catalog ?? []).length === 0 && <p className="text-xs text-muted-foreground">No catalog capabilities to reuse.</p>}
        </CardContent>
      </Card>

      <StepFooter
        summary={`${stagedCount} MCP tool${stagedCount === 1 ? "" : "s"} · ${reused.length} reused`}
        busy={busy} disabled={stagedCount + reused.length === 0} onNext={submit}
      />
    </div>
  );
}

// -- Step 4: bindings ----------------------------------------------------------
function BindingsStep({ session, onDone }: { session: OnboardingSession; onDone: (s: OnboardingSession) => void }) {
  const tasks = useMemo(() => [
    ...session.bpmn!.service_tasks.map((id) => ({ id, kind: "serviceTask" as const })),
    ...session.bpmn!.user_tasks.map((id) => ({ id, kind: "userTask" as const })),
  ], [session]);
  const capOptions = [...session.staged_capabilities.map((c) => `${c.capability_id}@^${c.version}`), ...session.reused_capability_refs];
  const { data: catalog } = useCapabilities();
  // HITL floor (rank) per capability_id: the stricter of its side-effect requirement
  // (approve_actions) and its declared min_hitl_mode. Mirrors the backend guard so
  // illegal modes are disabled up front, for both staged and reused capabilities.
  const policyByCap = useMemo(() => {
    const m: Record<string, { side_effect: string; floor: number }> = {};
    const add = (id: string, side_effect: string, minMode?: string | null) => {
      m[id] = { side_effect, floor: Math.max(side_effect === "side_effectful" ? 2 : 0, HITL_RANK[minMode ?? "none"] ?? 0) };
    };
    for (const c of (catalog ?? []) as any[]) add(c.capability_id, c.side_effect, c.constraints?.min_hitl_mode);
    for (const sc of session.staged_capabilities) add(sc.capability_id, sc.side_effect, sc.min_hitl_mode);
    return m;
  }, [catalog, session.staged_capabilities]);
  const capIdOf = (ref?: string | null) => (ref ? ref.split("@")[0] : undefined);
  const sideEffectOf = (ref?: string | null) => policyByCap[capIdOf(ref) ?? ""]?.side_effect;
  const floorOf = (ref?: string | null) => policyByCap[capIdOf(ref) ?? ""]?.floor ?? 0;

  const [rows, setRows] = useState<Record<string, BindingInput>>(() => {
    const init: Record<string, BindingInput> = {};
    for (const t of tasks) {
      const existing = session.bindings.find((b) => b.element_id === t.id);
      init[t.id] = existing
        ? { element_id: t.id, element_kind: t.kind, executor_type: existing.executor_type, capability_ref: existing.capability_ref, role: existing.role, hitl_mode: existing.hitl_mode, hitl_role: existing.hitl_role }
        : { element_id: t.id, element_kind: t.kind, executor_type: t.kind === "serviceTask" ? "capability" : "human", hitl_mode: "none" };
    }
    return init;
  });
  const [busy, setBusy] = useState(false);
  const [fieldErrs, setFieldErrs] = useState<Record<string, string>>({});

  const patch = (id: string, p: Partial<BindingInput>) => setRows((r) => ({ ...r, [id]: { ...r[id]!, ...p } as BindingInput }));
  // Picking a capability bumps HITL to its floor if the current mode is too weak.
  const chooseExecutor = (id: string, ref: string) => {
    const fl = floorOf(ref);
    const cur = rows[id]!.hitl_mode;
    const bumped = (HITL_RANK[cur] ?? 0) < fl ? (fl >= 2 ? "approve_actions" : "review_after") : cur;
    patch(id, { capability_ref: ref, hitl_mode: bumped });
  };

  async function submit() {
    setBusy(true); setFieldErrs({});
    try {
      onDone(await setOnboardingBindings(session.session_id, { bindings: tasks.map((t) => rows[t.id]!) }));
    } catch (e) {
      const x = extractErrors(e);
      const map: Record<string, string> = {};
      x.fields.forEach((f) => {
        const key = f.element_id ?? f.field;
        if (key) map[key] = (map[key] ? map[key] + "; " : "") + f.message;
      });
      setFieldErrs(map);
      const n = Object.keys(map).length;
      if (n) toast.error(`${n} binding${n === 1 ? "" : "s"} need fixing — see the highlighted rows.`);
      else if (x.general) toast.error(x.general);
    } finally { setBusy(false); }
  }

  const errorCount = Object.keys(fieldErrs).length;
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">Exactly one binding per BPMN task. Side-effectful capabilities lock HITL to <span className="font-mono">approve_actions</span> or stricter.</p>
      {errorCount > 0 && (
        <div className="flex items-center gap-2 rounded-md border border-danger/40 bg-danger-muted/20 p-3 text-sm text-danger">
          <XCircle className="size-4 shrink-0" />
          <span>{errorCount} binding{errorCount === 1 ? "" : "s"} rejected. Fix the highlighted rows below and save again.</span>
        </div>
      )}
      {tasks.map((t) => {
        const row = rows[t.id]!;
        const floor = row.executor_type === "capability" ? floorOf(row.capability_ref) : 0;
        return (
          <Card key={t.id} className={cn(fieldErrs[t.id] && "border-danger/60")}>
            <CardContent className="pt-5">
              <div className="mb-3 flex items-center gap-2">
                <span className="font-mono text-sm font-medium">{t.id}</span>
                <Badge variant="outline" className="text-[10px]">{t.kind}</Badge>
                <span className="text-xs text-muted-foreground">{session.bpmn!.task_names[t.id]}</span>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <Field label="Executor">
                  {t.kind === "serviceTask" ? (
                    <select className={selectCls} value={row.capability_ref ?? ""} onChange={(e) => chooseExecutor(t.id, e.target.value)}>
                      <option value="">Select…</option>
                      {capOptions.map((r) => <option key={r} value={r}>{r}{sideEffectOf(r) === "side_effectful" ? " · side-effectful" : ""}</option>)}
                    </select>
                  ) : (
                    <Input value={row.role ?? ""} onChange={(e) => patch(t.id, { role: e.target.value })} placeholder="role.payments.ops_analyst" className="font-mono text-xs" />
                  )}
                </Field>
                <Field label="HITL mode">
                  <select className={selectCls} value={row.hitl_mode} onChange={(e) => patch(t.id, { hitl_mode: e.target.value })}>
                    {HITL_MODES.map((m) => <option key={m} value={m} disabled={(HITL_RANK[m] ?? 0) < floor}>{m}{(HITL_RANK[m] ?? 0) < floor ? " (too weak)" : ""}</option>)}
                  </select>
                </Field>
                <Field label="Role">
                  {row.hitl_mode !== "none"
                    ? <Input value={row.hitl_role ?? ""} onChange={(e) => patch(t.id, { hitl_role: e.target.value })} placeholder="role.payments.ops_approver" className="font-mono text-xs" />
                    : <p className="py-2 text-xs text-muted-foreground">not required for mode none</p>}
                </Field>
              </div>
              {fieldErrs[t.id] && <p className="mt-2 text-xs text-danger">{fieldErrs[t.id]}</p>}
            </CardContent>
          </Card>
        );
      })}
      <StepFooter summary={`${tasks.length} task${tasks.length === 1 ? "" : "s"}`} busy={busy} onNext={submit} />
    </div>
  );
}

// -- Step 5: triage (predicate tree) ------------------------------------------
const OPS = ["eq", "ne", "in", "starts_with", "intersects", "exists", "gt", "gte", "lt", "lte"];

function toPredicate(n: any): Record<string, unknown> {
  if (n.leaf) {
    let value: unknown = n.value;
    if (n.op === "in" || n.op === "intersects") value = n.value.split(",").map((x: string) => x.trim()).filter(Boolean);
    else if (n.op === "exists") value = n.value === "true";
    else if (["gt", "gte", "lt", "lte"].includes(n.op) && n.value !== "" && !isNaN(Number(n.value))) value = Number(n.value);
    return { field: n.field, op: n.op, value };
  }
  if (n.kind === "not") return { not: toPredicate(n.children[0] ?? { leaf: true, field: "reason_code", op: "eq", value: "" }) };
  return { [n.kind]: n.children.map(toPredicate) };
}

function TriageStep({ session, onDone }: { session: OnboardingSession; onDone: (s: OnboardingSession) => void }) {
  const [ruleId, setRuleId] = useState(session.triage_rules[0]?.rule_id ?? "triage-rule-1");
  const [priority, setPriority] = useState(session.triage_rules[0]?.priority ?? 100);
  const [tree, setTree] = useState<any>({ kind: "all", children: [{ leaf: true, field: "reason_code", op: "eq", value: "AC01" }] });
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    try {
      const rule: OnbTriageRule = { rule_id: ruleId, priority, when: toPredicate(tree) };
      onDone(await setOnboardingTriage(session.session_id, { triage_rules: [rule] }));
    } catch (e) {
      toast.error(extractErrors(e).fields.map((f) => f.message).join("; ") || extractErrors(e).general);
    } finally { setBusy(false); }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle>Triage rule</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-4">
            <Field label="Rule id"><Input value={ruleId} onChange={(e) => setRuleId(e.target.value)} className="font-mono text-xs" /></Field>
            <Field label="Priority"><Input type="number" value={priority} onChange={(e) => setPriority(Number(e.target.value))} /></Field>
          </div>
          <PredicateEditor node={tree} onChange={setTree} depth={0} onRemove={undefined} />
        </CardContent>
      </Card>
      <StepFooter summary="predicate over envelope fields" busy={busy} onNext={submit} />
    </div>
  );
}

function PredicateEditor({ node, onChange, depth, onRemove }: { node: any; onChange: (n: any) => void; depth: number; onRemove?: () => void }) {
  if (node.leaf) {
    return (
      <div className="flex flex-wrap items-center gap-2 rounded-md border border-border p-2" style={{ marginLeft: depth * 20 }}>
        <Input value={node.field} onChange={(e) => onChange({ ...node, field: e.target.value })} className="h-8 w-40 font-mono text-xs" placeholder="reason_code" />
        <select className={cn(selectCls, "h-8 w-28")} value={node.op} onChange={(e) => onChange({ ...node, op: e.target.value })}>
          {OPS.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        <Input value={node.value} onChange={(e) => onChange({ ...node, value: e.target.value })} className="h-8 w-40 font-mono text-xs" placeholder="value" />
        <div className="flex-1" />
        {onRemove && <Button variant="ghost" size="icon" className="size-8" onClick={onRemove}><Trash2 className="size-3.5" /></Button>}
      </div>
    );
  }
  const setChild = (i: number, c: any) => onChange({ ...node, children: node.children.map((x: any, j: number) => j === i ? c : x) });
  const removeChild = (i: number) => onChange({ ...node, children: node.children.filter((_: any, j: number) => j !== i) });
  return (
    <div className="space-y-2 rounded-md border border-process/30 p-2" style={{ marginLeft: depth * 20 }}>
      <div className="flex items-center gap-2">
        <div className="flex gap-1">
          {(["all", "any", "not"] as const).map((k) => (
            <button key={k} onClick={() => onChange({ ...node, kind: k, children: k === "not" ? node.children.slice(0, 1) : node.children })}
              className={cn("rounded px-2 py-1 text-xs", node.kind === k ? "bg-foreground text-background" : "border border-border text-muted-foreground")}>{k.toUpperCase()}</button>
          ))}
        </div>
        <div className="flex-1" />
        {node.kind !== "not" && (
          <>
            <Button variant="outline" size="sm" onClick={() => onChange({ ...node, children: [...node.children, { leaf: true, field: "amount", op: "gte", value: "0" }] })}><Plus className="mr-1 size-3" />Condition</Button>
            <Button variant="outline" size="sm" onClick={() => onChange({ ...node, children: [...node.children, { kind: "any", children: [] }] })}><Plus className="mr-1 size-3" />Group</Button>
          </>
        )}
        {onRemove && <Button variant="ghost" size="icon" className="size-8" onClick={onRemove}><Trash2 className="size-3.5" /></Button>}
      </div>
      {node.children.map((c: any, i: number) => (
        <PredicateEditor key={i} node={c} depth={depth + 1} onChange={(nc) => setChild(i, nc)} onRemove={() => removeChild(i)} />
      ))}
    </div>
  );
}

// -- Step 6: policies ----------------------------------------------------------
function PoliciesStep({ session, onDone }: { session: OnboardingSession; onDone: (s: OnboardingSession) => void }) {
  const gateways = session.bpmn!.gateways;
  const tasks = [...session.bpmn!.service_tasks, ...session.bpmn!.user_tasks];
  const artifacts = Array.from(new Set(session.staged_artifacts.map((a) => a.artifact_key)));
  const [gvars, setGvars] = useState<Record<string, { variable: string; source_artifact: string }>>(
    () => Object.fromEntries(gateways.map((g) => {
      const ex = session.gateway_variables.find((v) => v.gateway_id === g);
      return [g, { variable: ex?.variable ?? "", source_artifact: ex?.source_artifact ?? "" }];
    })),
  );
  const [sod, setSod] = useState<string[][]>(session.sod_policies.map((s) => s.elements));
  const [roles, setRoles] = useState<string[]>(session.roles);
  const [roleInput, setRoleInput] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    try {
      const gateway_variables = gateways
        .filter((g) => gvars[g]!.variable && gvars[g]!.source_artifact)
        .map((g) => ({ gateway_id: g, variable: gvars[g]!.variable, source_artifact: gvars[g]!.source_artifact }));
      onDone(await setOnboardingPolicies(session.session_id, {
        gateway_variables, sod_policies: sod.filter((e) => e.length >= 2).map((elements) => ({ elements })), roles,
      }));
    } catch (e) { toast.error(extractErrors(e).general || "Could not save policies."); }
    finally { setBusy(false); }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle>Gateway variables</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {gateways.length === 0 && <p className="text-sm text-muted-foreground">No exclusive gateways in this process.</p>}
          {gateways.map((g) => (
            <div key={g} className="grid grid-cols-2 gap-3 rounded-md border border-border p-3">
              <p className="col-span-2 font-mono text-xs font-medium">{g}</p>
              <Field label="Decision variable (dot-path)"><Input value={gvars[g]!.variable} onChange={(e) => setGvars({ ...gvars, [g]: { ...gvars[g]!, variable: e.target.value } })} placeholder="beneficiary.repair_verdict" className="font-mono text-xs" /></Field>
              <Field label="Source artifact">
                <select className={selectCls} value={gvars[g]!.source_artifact} onChange={(e) => setGvars({ ...gvars, [g]: { ...gvars[g]!, source_artifact: e.target.value } })}>
                  <option value="">Select…</option>
                  {artifacts.map((a) => <option key={a} value={a}>{a}</option>)}
                </select>
              </Field>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Separation of duties</CardTitle>
          <Button variant="outline" size="sm" onClick={() => setSod([...sod, []])}><Plus className="mr-1 size-3" />Add constraint</Button>
        </CardHeader>
        <CardContent className="space-y-3">
          {sod.length === 0 && <p className="text-sm text-muted-foreground">Four-eyes: the actors on the chosen tasks must be distinct.</p>}
          {sod.map((elements, i) => (
            <div key={i} className="rounded-md border border-border p-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs uppercase tracking-wide text-muted-foreground">distinct_actor</span>
                <Button variant="ghost" size="icon" className="size-7" onClick={() => setSod(sod.filter((_, j) => j !== i))}><Trash2 className="size-3.5" /></Button>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {tasks.map((t) => {
                  const on = elements.includes(t);
                  return <button key={t} onClick={() => setSod(sod.map((el, j) => j === i ? (on ? el.filter((x) => x !== t) : [...el, t]) : el))}
                    className={cn("rounded px-2 py-1 font-mono text-xs", on ? "bg-foreground text-background" : "border border-border text-muted-foreground")}>{t}</button>;
                })}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Pack roles</CardTitle></CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-center gap-2">
            {roles.map((r) => (
              <span key={r} className="flex items-center gap-1.5 rounded bg-surface px-2 py-1 font-mono text-xs">
                {r}<button onClick={() => setRoles(roles.filter((x) => x !== r))}><XCircle className="size-3 text-muted-foreground" /></button>
              </span>
            ))}
            <Input value={roleInput} onChange={(e) => setRoleInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && roleInput.trim()) { setRoles(Array.from(new Set([...roles, roleInput.trim()]))); setRoleInput(""); } }}
              placeholder="role.payments.ops_approver + Enter" className="w-64 font-mono text-xs" />
          </div>
        </CardContent>
      </Card>

      <StepFooter summary="gateway variables · SoD · roles" busy={busy} onNext={submit} nextLabel="Save & review" />
    </div>
  );
}

// -- Step 7: review / validate / activate -------------------------------------
function ReviewStep({ session, onChange, goStep }: { session: OnboardingSession; onChange: (s: OnboardingSession) => void; goStep: (i: number) => void }) {
  const [busy, setBusy] = useState<"assemble" | "commit" | null>(null);
  const report = session.dry_run_report ?? null;
  const errorCount = report ? countBySeverity(report.findings).error : 0;
  const done = session.state === "completed";

  async function assemble() {
    setBusy("assemble");
    try { onChange(await assembleOnboarding(session.session_id)); }
    catch (e) { toast.error(extractErrors(e).general || "Assemble failed."); }
    finally { setBusy(null); }
  }
  async function activate() {
    setBusy("commit");
    try {
      const s = await commitOnboarding(session.session_id);
      onChange(s);
      if (s.state === "completed") toast.success(`${s.result_pack} activated — joined live triage.`);
    } catch (e) {
      const x = extractErrors(e);
      onChange(await getOnboardingSession(session.session_id)); // refresh commit_progress
      toast.error(x.general || "Activation failed — see validation findings.");
    } finally { setBusy(null); }
  }

  if (done) {
    return (
      <Card className="border-success/50 bg-success-muted/10">
        <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
          <span className="flex size-14 items-center justify-center rounded-full bg-success text-success-foreground"><Check className="size-7" /></span>
          <h2 className="text-xl font-light">Pack activated</h2>
          <p className="text-sm text-muted-foreground"><span className="font-mono">{session.result_pack}</span> is live and joined triage.</p>
          <div className="flex gap-2">
            <Button asChild><Link to={`/registry/packs/${session.basics.pack_key}/${session.basics.version}`}>Open pack</Link></Button>
            <Button variant="outline" asChild><Link to="/registry">Back to registry</Link></Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle>Review</CardTitle></CardHeader>
        <CardContent className="grid grid-cols-3 gap-4">
          <ReadRow label="Pack" value={`${session.basics.pack_key}@${session.basics.version}`} mono />
          <ReadRow label="BPMN · tasks" value={`${session.bpmn?.bpmn_file ?? "—"} · ${(session.bpmn?.service_tasks.length ?? 0) + (session.bpmn?.user_tasks.length ?? 0)} bound`} />
          <ReadRow label="Dependencies" value={`${session.staged_capabilities.length + session.reused_capability_refs.length} caps · ${session.staged_artifacts.length} new artifacts`} />
          <details className="col-span-3">
            <summary className="cursor-pointer text-sm text-agent">View manifest JSON</summary>
            <pre className="mt-2 overflow-auto rounded-md bg-surface p-3 text-[11px]">{JSON.stringify(manifestPreview(session), null, 2)}</pre>
          </details>
        </CardContent>
      </Card>

      {report && <ReportView report={report} goStep={goStep} />}
      {session.commit_progress.length > 0 && <CommitProgress steps={session.commit_progress} />}

      <div className="flex items-center gap-3">
        <Button variant="outline" disabled={busy !== null} onClick={assemble}>
          {busy === "assemble" ? <Loader2 className="mr-1 size-4 animate-spin" /> : null}{report ? "Re-validate" : "Validate"}
        </Button>
        <Button variant="success" disabled={busy !== null || !report || errorCount > 0} onClick={activate}
          title={!report ? "Validate first" : errorCount > 0 ? "Resolve all errors first" : ""}>
          {busy === "commit" ? <Loader2 className="mr-1 size-4 animate-spin" /> : <Check className="mr-1 size-4" />} Activate pack
        </Button>
        <span className="text-sm text-muted-foreground">Activation pins every dependency and flips the pack to <span className="font-medium">active</span>.</span>
      </div>
    </div>
  );
}

function CommitProgress({ steps }: { steps: OnboardingSession["commit_progress"] }) {
  return (
    <Card>
      <CardHeader><CardTitle>Commit chain</CardTitle></CardHeader>
      <CardContent className="space-y-1">
        {steps.map((s) => (
          <div key={s.key} className="flex items-center gap-3 py-1.5 text-sm">
            {s.status === "done" ? <Check className="size-4 text-success" />
              : s.status === "running" ? <Loader2 className="size-4 animate-spin text-agent" />
              : s.status === "failed" ? <XCircle className="size-4 text-danger" />
              : <span className="size-4 rounded-full border border-border" />}
            <span className={cn(s.status === "failed" && "text-danger")}>{s.label}</span>
            {s.detail && <span className="text-xs text-muted-foreground">· {s.detail}</span>}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function ReportView({ report, goStep }: { report: ValidationReport; goStep?: (i: number) => void }) {
  const counts = countBySeverity(report.findings);
  const groups = groupByStage(report.findings);
  const stageToStep: Record<number, number> = { 1: 1, 2: 3, 3: 2, 4: 3, 5: 3, 6: 5, 7: 4 };
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
            <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">Stage {g.stage} · {g.name}</p>
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
                  {goStep && f.severity === "error" && (
                    <Button variant="ghost" size="sm" onClick={() => goStep(stageToStep[f.stage] ?? 0)}>Fix</Button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

// -- shared little pieces -----------------------------------------------------
function manifestPreview(s: OnboardingSession) {
  return {
    pack_key: s.basics.pack_key, version: s.basics.version, title: s.basics.title,
    process: s.bpmn ? { bpmn_file: s.bpmn.bpmn_file, process_id: s.bpmn.process_id } : null,
    requires_capabilities: [...s.staged_capabilities.map((c) => `${c.capability_id}@^${c.version}`), ...s.reused_capability_refs],
    bindings: s.bindings.length, triage_rules: s.triage_rules.map((r) => r.rule_id),
  };
}
function BackLink() {
  return (
    <div className="mb-4">
      <Link to="/registry" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> Registry
      </Link>
    </div>
  );
}
function Field({ label, hint, error, className, children }: { label: string; hint?: string; error?: string; className?: string; children: React.ReactNode }) {
  return (
    <div className={className}>
      <Label className="mb-1.5 flex items-center gap-2">{label}{hint && <span className="text-xs font-normal text-muted-foreground">· {hint}</span>}</Label>
      {children}
      {error && <p className="mt-1 text-xs text-danger">{error}</p>}
    </div>
  );
}
function ReadRow({ label, value, mono, className }: { label: string; value: string; mono?: boolean; className?: string }) {
  return (
    <div className={className}>
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={cn("mt-0.5 text-sm", mono && "font-mono")}>{value}</p>
    </div>
  );
}
function StepFooter({ summary, busy, disabled, onNext, nextLabel = "Save & continue" }: { summary: string; busy: boolean; disabled?: boolean; onNext: () => void; nextLabel?: string }) {
  return (
    <div className="flex items-center justify-between border-t border-border pt-4">
      <span className="text-sm text-muted-foreground">{summary}</span>
      <Button disabled={busy || disabled} onClick={onNext}>
        {busy ? <Loader2 className="mr-1 size-4 animate-spin" /> : null}{nextLabel} <ArrowRight className="ml-1 size-4" />
      </Button>
    </div>
  );
}
function EmptyBox({ title, body }: { title: string; body: string }) {
  return <Card><CardContent className="py-10 text-center"><p className="text-sm font-medium">{title}</p>{body && <p className="mt-1 text-sm text-muted-foreground">{body}</p>}</CardContent></Card>;
}
function SeverityIcon({ severity }: { severity: string }) {
  if (severity === "error") return <XCircle className="mt-0.5 size-4 shrink-0 text-danger" />;
  if (severity === "warning") return <AlertTriangle className="mt-0.5 size-4 shrink-0 text-attention" />;
  return <Info className="mt-0.5 size-4 shrink-0 text-artifact" />;
}
