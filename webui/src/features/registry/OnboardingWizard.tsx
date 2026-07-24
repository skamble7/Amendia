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
import { BpmnViewer, type BpmnMarker } from "./BpmnViewer";
import { ApiError } from "@/api/client";
import { groupByStage, countBySeverity, SEVERITY_VARIANT } from "@/lib/validation";
import { cn } from "@/lib/utils";
import {
  assembleOnboarding, attachOnboardingBpmn, commitOnboarding, createOnboardingSession,
  getOnboardingSession, introspectMcp, setOnboardingBindings, setOnboardingCapabilities,
  setOnboardingPolicies, setOnboardingTriage,
  type BindingInput, type CapabilityToolSelection, type IntrospectedTool, type OnbTriageRule,
  type OnbBpmnInventory, type OnbBindableElement, type OnboardingSession, type OnboardingState,
  type ValidationReport, type InferenceDraft, type OnbDecisionSpec, type OnbReduceSpec,
} from "@/api/services/registry";
import { useCapabilities, useCapabilitySearch, useOnboardingSessions, usePacks } from "./queries";

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
type FieldError = { field?: string; element_id?: string; capability_id?: string; allowed_min_mode?: string; message: string };
function extractErrors(err: unknown): { general: string; fields: FieldError[]; findings: any[] } {
  if (!(err instanceof ApiError)) return { general: "Unexpected error.", fields: [], findings: [] };
  const d = err.detail as any;
  if (typeof d === "string") return { general: d, fields: [], findings: [] };
  const fields: FieldError[] = Array.isArray(d?.errors)
    ? d.errors.map((e: any) => ({
        field: e.field ?? e.tool ?? e.ref ?? e.rule_id,
        element_id: e.element_id, capability_id: e.capability_id,
        allowed_min_mode: e.allowed_min_mode, message: e.message,
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
  const [form, setForm] = useState({ pack_key: "", version: "1.0.0", title: "", description: "", default_domain: "" });
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
          <Field label="Default domain" hint="the cap.<domain>.<tool> id namespace — keep it process-scoped to avoid clashing with the active catalog; leave blank to derive it from the pack key" error={err("default_domain")}>
            <Input value={form.default_domain} onChange={(e) => setForm({ ...form, default_domain: e.target.value })} placeholder="derives from pack key if blank" />
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
/** ADR-027: coverage markers from the server classification (never a client set-diff). */
function coverageMarkers(inv: OnbBpmnInventory): BpmnMarker[] {
  // ADR-044 (Track 1): mark the FULL bindable set executable (task kinds + message + callActivity),
  // not just service/user tasks — everything on the sequence flow executes (single fidelity).
  const execIds = [...inv.bindable_elements.map((e) => e.element_id), ...inv.gateways];
  const exec: BpmnMarker[] = execIds.map((id) => ({ elementId: id, state: "executable" }));
  const docs: BpmnMarker[] = (inv.documented_elements ?? [])
    .filter((d) => d.element_id)
    .map((d) => ({ elementId: d.element_id!, state: d.tier === "unknown" ? "unknown" : "documented" }));
  return [...exec, ...docs];
}

function BpmnStep({ session, onDone }: { session: OnboardingSession; onDone: (s: OnboardingSession) => void }) {
  const [xml, setXml] = useState("");
  const [fileName, setFileName] = useState("");
  const [busy, setBusy] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [findings, setFindings] = useState<any[]>([]);
  const [general, setGeneral] = useState("");
  // The parsed session + the XML it was parsed from — shown as a coverage preview before advancing.
  const [result, setResult] = useState<OnboardingSession | null>(session.bpmn ? session : null);
  const [attachedXml, setAttachedXml] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  // Batch-1 UX: once a BPMN parses, collapse the (tall) input and bring the coverage/diagram into focus.
  const [collapsed, setCollapsed] = useState(!!session.bpmn);
  const coverageRef = useRef<HTMLDivElement>(null);

  async function loadFile(file: File | undefined | null) {
    if (!file) return;
    const text = await file.text();
    setXml(text); setFileName(file.name); setFindings([]); setGeneral(""); setResult(null);
  }

  async function submit() {
    setBusy(true); setFindings([]); setGeneral(""); setResult(null);
    try {
      const s = await attachOnboardingBpmn(session.session_id, { bpmn_xml: xml, bpmn_file: fileName || undefined });
      setResult(s); setAttachedXml(xml); setCollapsed(true);
      // let the coverage card mount, then scroll it into focus.
      setTimeout(() => coverageRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
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
        {collapsed && result?.bpmn ? (
          <CardContent>
            <div className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-surface/40 p-3 text-sm">
              <Check className="size-4 text-success" />
              <span className="font-medium">BPMN attached</span>
              <span className="font-mono text-xs text-muted-foreground">· {fileName || "pasted"}</span>
              <span className="text-xs text-muted-foreground">· {result.bpmn.coverage_counts?.executable ?? 0} executable, {result.bpmn.coverage_counts?.documented ?? 0} documented</span>
              <div className="flex-1" />
              <Button variant="ghost" size="sm" onClick={() => setCollapsed(false)}><FileCode className="mr-1 size-3.5" />Replace / edit</Button>
            </div>
          </CardContent>
        ) : (
        <CardContent className="space-y-3">
          <Label>Upload or paste a BPMN 2.0 XML. Full BPMN is accepted — anything outside the executable subset is kept as <span className="font-medium">documented</span> and shown in the coverage report below.</Label>

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
                <div className="text-xs text-muted-foreground">or use the picker · full BPMN 2.0</div>
                <Button variant="secondary" size="sm" className="mt-1" onClick={() => inputRef.current?.click()}>
                  <Upload className="mr-1 size-4" /> Choose file
                </Button>
              </>
            )}
          </div>

          <Textarea
            id="bpmn" value={xml}
            onChange={(e) => { setXml(e.target.value); setFileName(""); setResult(null); }}
            rows={12} className="font-mono text-xs" placeholder="…or paste <bpmn:definitions …> here"
          />
          {general && <p className="text-sm text-danger">{general}</p>}
          {findings.length > 0 && (
            <div className="rounded-md border border-danger/40 bg-danger-muted/20 p-3">
              <p className="mb-1 text-sm font-medium text-danger">BPMN rejected — fix these to continue</p>
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
            <Button disabled={busy || !xml.trim()} onClick={submit}>{busy ? <><Loader2 className="mr-1 size-4 animate-spin" /> Parsing…</> : "Parse & preview coverage"}</Button>
          </div>
        </CardContent>
        )}
      </Card>
      {result?.bpmn && (
        <div ref={coverageRef}>
          <CoverageCard inv={result.bpmn} inferred={result.inferred ?? null} xml={attachedXml} onContinue={() => onDone(result)} />
        </div>
      )}
    </div>
  );
}

/** The BPMN conformance level this diagram needs (derived server-side, ADR-034). Two levels:
 * `common_executable` (uses parallel / timers / error boundaries / messages / sub-processes / the
 * full task set) vs the conservative `common_subset`. Retired granular values normalize to
 * `common_executable`. */
const _EXECUTABLE = "Uses beyond-subset BPMN (parallel, timers/SLA, error boundaries, messages, "
  + "sub-processes, or the full task set) — runs only on a runtime at the common_executable level.";

function ProfileBadge({ profile }: { profile?: string }) {
  const p = profile ?? "common_subset";
  if (p !== "common_subset") {
    return (
      <Badge variant="process" className="text-[11px]" title={_EXECUTABLE}>
        Requires common_executable
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="text-[11px] text-muted-foreground" title="Runs on the conservative common_subset level (Phase-0/1 base subset).">
      common_subset
    </Badge>
  );
}

const COVERAGE_TIERS: { key: string; label: string; dot: string; hint: string }[] = [
  { key: "executable", label: "Executable", dot: "bg-success", hint: "runs today" },
  { key: "documented", label: "Documented", dot: "bg-attention", hint: "accepted, not executed yet" },
  { key: "unknown", label: "Unknown", dot: "bg-muted-foreground", hint: "unrecognized element" },
];

function CoverageCard({ inv, inferred, xml, onContinue }: { inv: OnbBpmnInventory; inferred: InferenceDraft | null; xml: string; onContinue: () => void }) {
  const counts = inv.coverage_counts ?? {};
  const markers = useMemo(() => coverageMarkers(inv), [inv]);
  const docs = inv.documented_elements ?? [];
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
      <CardHeader className="flex-row items-center justify-between">
        <div className="flex items-center gap-2">
          <CardTitle>Coverage · {inv.process_id}</CardTitle>
          <ProfileBadge profile={inv.required_execution_profile} />
        </div>
        <Button size="sm" onClick={onContinue}>Continue to capabilities <ArrowRight className="ml-1 size-4" /></Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* legend + counts */}
        <div className="flex flex-wrap gap-4 text-xs">
          {COVERAGE_TIERS.map((t) => (
            <span key={t.key} className="flex items-center gap-1.5">
              <span className={cn("size-2.5 rounded-full", t.dot)} />
              <span className="font-medium">{t.label}</span>
              <span className="tabular-nums text-muted-foreground">{counts[t.key] ?? 0}</span>
              <span className="text-muted-foreground/70">· {t.hint}</span>
            </span>
          ))}
        </div>

        {xml && <BpmnViewer xml={xml} markers={markers} className="h-[420px]" />}

        <div className="grid grid-cols-3 gap-4">
          {group("Capability tasks", inv.bindable_elements.filter((e) => e.category === "capability").map((e) => e.element_id), "agent")}
          {group("Human tasks", inv.bindable_elements.filter((e) => e.category === "human").map((e) => e.element_id), "attention")}
          {group("Gateways", inv.gateways, "process")}
          {inv.bindable_elements.some((e) => e.category === "message") &&
            group("Message", inv.bindable_elements.filter((e) => e.category === "message").map((e) => e.element_id), "process")}
          {inv.bindable_elements.some((e) => e.category === "call") &&
            group("Call activities", inv.bindable_elements.filter((e) => e.category === "call").map((e) => e.element_id), "artifact")}
        </div>

        {/* ADR-032 Phase 2.6: embedded sub-processes rendered as executable groups (members nested). */}
        {(inv.subprocesses ?? []).length > 0 && (
          <div>
            <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <Boxes className="size-3.5" /> Sub-processes · {(inv.subprocesses ?? []).length}
            </p>
            <div className="space-y-2">
              {(inv.subprocesses ?? []).map((sp) => (
                <div key={sp.id} className="rounded-md border border-process/30 bg-process/5 p-2">
                  <p className="mb-1 text-xs font-medium">{sp.name || sp.id} <span className="text-muted-foreground">(inlined)</span></p>
                  <div className="flex flex-wrap gap-1">
                    {(sp.member_ids ?? []).map((id) => (
                      <Badge key={id} variant="outline" className="font-mono text-[10px]">{id}</Badge>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {inferred && (inferred.roles.length > 0 || inferred.bindings.length > 0 || inferred.annotations.length > 0) && (
          <div className="rounded-md border border-agent/30 bg-agent/5 p-3">
            <p className="mb-1.5 flex items-center gap-1.5 text-sm font-medium text-agent">
              <Boxes className="size-4" /> Inferred from your diagram
            </p>
            <p className="text-xs text-muted-foreground">
              {inferred.roles.length} role{inferred.roles.length === 1 ? "" : "s"} (from lanes) ·
              {" "}{inferred.bindings.length} binding scaffold{inferred.bindings.length === 1 ? "" : "s"} ·
              {" "}{inferred.gateway_variables.length} gateway variable{inferred.gateway_variables.length === 1 ? "" : "s"} ·
              {" "}{inferred.capability_candidates.length} capability candidate{inferred.capability_candidates.length === 1 ? "" : "s"}.
              These pre-fill the next steps — every value shows its source and stays editable; nothing is committed until you submit each step.
            </p>
            {inferred.annotations.length > 0 && (
              <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
                {inferred.annotations.map((a, i) => (
                  <li key={i} className="flex items-start gap-1.5">
                    <Info className="mt-0.5 size-3 shrink-0" />
                    <span>{a.message}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {docs.length > 0 && (
          <div>
            <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <Info className="size-3.5" /> Documented — not executed today (ADR-027)
            </p>
            <div className="flex flex-wrap gap-1.5">
              {docs.map((d, i) => (
                <Badge key={i} variant={d.tier === "unknown" ? "outline" : "attention"} className="font-mono text-[11px]">
                  {d.kind}{d.element_id ? ` · ${d.element_id}` : ""}
                </Badge>
              ))}
            </div>
            <p className="mt-1.5 text-xs text-muted-foreground">
              These are kept for documentation. If any sits on the live sequence-flow path it will block activation until execution grows to cover it.
            </p>
          </div>
        )}
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
// -- ADR-046 (Track 2): inline decision / reduce capability builders ----------
const HIT_POLICIES = ["UNIQUE", "FIRST", "PRIORITY", "ANY", "COLLECT"] as const;
const DMN_TYPES = ["string", "number", "boolean"] as const;
const REDUCE_OPS = ["any", "all", "none", "count", "sum", "avg", "min", "max", "first", "last"] as const;
const PREDICATE_OPS = new Set(["any", "all", "none"]);

type DecisionDraft = {
  capability_id: string; input_artifact_key: string; input_name: string;
  output_artifact_key: string; output_name: string; hit_policy: string;
  inputs: { expression: string; type: string }[];
  outputs: { name: string; type: string }[];
  rules: { when: string[]; then: string[] }[];
};
type ReduceDraft = {
  capability_id: string; input_artifact_key: string; output_artifact_key: string;
  op: string; source: string; item_path: string; predicate: string; output_field: string;
};

function newDecision(id = ""): DecisionDraft {
  return {
    capability_id: id, input_artifact_key: "", input_name: "in",
    output_artifact_key: "", output_name: "verdict", hit_policy: "UNIQUE",
    inputs: [{ expression: "", type: "string" }], outputs: [{ name: "verdict", type: "string" }],
    rules: [{ when: [""], then: [""] }],
  };
}
function decisionToSpec(d: DecisionDraft): OnbDecisionSpec {
  return {
    capability_id: d.capability_id, capability_version: "1.0.0",
    input_artifact_key: d.input_artifact_key, input_name: d.input_name || "in",
    output_artifact_key: d.output_artifact_key, output_name: d.output_name || "verdict", output_version: "1.0.0",
    table: { hit_policy: d.hit_policy, inputs: d.inputs, outputs: d.outputs, rules: d.rules },
  };
}
function reduceToSpec(r: ReduceDraft): OnbReduceSpec {
  return {
    capability_id: r.capability_id, capability_version: "1.0.0",
    input_artifact_key: r.input_artifact_key, input_name: "in",
    output_artifact_key: r.output_artifact_key, output_name: "summary", output_version: "1.0.0",
    config: { op: r.op, source: r.source || undefined, item_path: r.item_path || undefined,
              predicate: r.predicate || undefined, output_field: r.output_field || "result" },
  };
}

function ArtifactKeyInput({ value, onChange, keys, placeholder }: { value: string; onChange: (v: string) => void; keys: string[]; placeholder: string }) {
  const listId = useMemo(() => "art-" + Math.random().toString(36).slice(2, 8), []);
  return (
    <>
      <Input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} list={listId} className="font-mono text-xs" />
      <datalist id={listId}>{keys.map((k) => <option key={k} value={k} />)}</datalist>
    </>
  );
}

function DecisionBuilder({ draft, onChange, onRemove, artifactKeys, error }: {
  draft: DecisionDraft; onChange: (d: DecisionDraft) => void; onRemove: () => void; artifactKeys: string[]; error?: string;
}) {
  const set = (p: Partial<DecisionDraft>) => onChange({ ...draft, ...p });
  const addInput = () => set({ inputs: [...draft.inputs, { expression: "", type: "string" }], rules: draft.rules.map((r) => ({ ...r, when: [...r.when, ""] })) });
  const rmInput = (i: number) => set({ inputs: draft.inputs.filter((_, j) => j !== i), rules: draft.rules.map((r) => ({ ...r, when: r.when.filter((_, j) => j !== i) })) });
  const addOutput = () => set({ outputs: [...draft.outputs, { name: "", type: "string" }], rules: draft.rules.map((r) => ({ ...r, then: [...r.then, ""] })) });
  const rmOutput = (i: number) => set({ outputs: draft.outputs.filter((_, j) => j !== i), rules: draft.rules.map((r) => ({ ...r, then: r.then.filter((_, j) => j !== i) })) });
  const addRule = () => set({ rules: [...draft.rules, { when: draft.inputs.map(() => ""), then: draft.outputs.map(() => "") }] });
  const setCell = (ri: number, which: "when" | "then", ci: number, v: string) =>
    set({ rules: draft.rules.map((r, j) => j === ri ? { ...r, [which]: r[which].map((x, k) => k === ci ? v : x) } : r) });
  return (
    <Card className={cn(error && "border-danger/60")}>
      <CardContent className="space-y-3 pt-4">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">Decision table</span>
          <Button variant="ghost" size="icon" className="size-7" onClick={onRemove}><Trash2 className="size-3.5" /></Button>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Capability id"><Input value={draft.capability_id} onChange={(e) => set({ capability_id: e.target.value })} placeholder="cap.payment.classify" className="font-mono text-xs" /></Field>
          <Field label="Hit policy">
            <select className={selectCls} value={draft.hit_policy} onChange={(e) => set({ hit_policy: e.target.value })}>{HIT_POLICIES.map((h) => <option key={h} value={h}>{h}</option>)}</select>
          </Field>
          <Field label="Reads artifact"><ArtifactKeyInput value={draft.input_artifact_key} onChange={(v) => set({ input_artifact_key: v })} keys={artifactKeys} placeholder="art.payment.enriched" /></Field>
          <Field label="Verdict artifact key"><Input value={draft.output_artifact_key} onChange={(e) => set({ output_artifact_key: e.target.value })} placeholder="art.payment.classify_verdict" className="font-mono text-xs" /></Field>
        </div>

        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground">Inputs (expression → type)</p>
          {draft.inputs.map((inp, i) => (
            <div key={i} className="flex gap-1">
              <Input value={inp.expression} onChange={(e) => set({ inputs: draft.inputs.map((x, j) => j === i ? { ...x, expression: e.target.value } : x) })} placeholder={`${draft.input_name}.gpi_status`} className="h-7 font-mono text-[11px]" />
              <select className={cn(selectCls, "h-7 w-24 text-[11px]")} value={inp.type} onChange={(e) => set({ inputs: draft.inputs.map((x, j) => j === i ? { ...x, type: e.target.value } : x) })}>{DMN_TYPES.map((t) => <option key={t}>{t}</option>)}</select>
              <Button variant="ghost" size="icon" className="size-7" onClick={() => rmInput(i)} disabled={draft.inputs.length <= 1}><Trash2 className="size-3" /></Button>
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={addInput}><Plus className="mr-1 size-3" />input</Button>
        </div>

        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground">Outputs (name → type)</p>
          {draft.outputs.map((o, i) => (
            <div key={i} className="flex gap-1">
              <Input value={o.name} onChange={(e) => set({ outputs: draft.outputs.map((x, j) => j === i ? { ...x, name: e.target.value } : x) })} placeholder="verdict" className="h-7 font-mono text-[11px]" />
              <select className={cn(selectCls, "h-7 w-24 text-[11px]")} value={o.type} onChange={(e) => set({ outputs: draft.outputs.map((x, j) => j === i ? { ...x, type: e.target.value } : x) })}>{DMN_TYPES.map((t) => <option key={t}>{t}</option>)}</select>
              <Button variant="ghost" size="icon" className="size-7" onClick={() => rmOutput(i)} disabled={draft.outputs.length <= 1}><Trash2 className="size-3" /></Button>
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={addOutput}><Plus className="mr-1 size-3" />output</Button>
        </div>

        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground">Rules (each input cell = a unary test: <span className="font-mono">"lit"</span> · <span className="font-mono">&lt; 1000</span> · <span className="font-mono">[1..9]</span> · <span className="font-mono">-</span>)</p>
          {draft.rules.map((r, ri) => (
            <div key={ri} className="flex flex-wrap items-center gap-1 rounded border border-border p-1">
              {r.when.map((c, ci) => <Input key={"w" + ci} value={c} onChange={(e) => setCell(ri, "when", ci, e.target.value)} placeholder="unary test" className="h-7 w-28 font-mono text-[11px]" />)}
              <span className="text-xs text-muted-foreground">→</span>
              {r.then.map((c, ci) => <Input key={"t" + ci} value={c} onChange={(e) => setCell(ri, "then", ci, e.target.value)} placeholder="value" className="h-7 w-28 font-mono text-[11px]" />)}
              <div className="flex-1" />
              <Button variant="ghost" size="icon" className="size-7" onClick={() => set({ rules: draft.rules.filter((_, j) => j !== ri) })} disabled={draft.rules.length <= 1}><Trash2 className="size-3" /></Button>
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={addRule}><Plus className="mr-1 size-3" />rule</Button>
        </div>
        {error && <p className="text-xs text-danger">{error}</p>}
      </CardContent>
    </Card>
  );
}

function ReduceBuilder({ draft, onChange, onRemove, artifactKeys, error }: {
  draft: ReduceDraft; onChange: (d: ReduceDraft) => void; onRemove: () => void; artifactKeys: string[]; error?: string;
}) {
  const set = (p: Partial<ReduceDraft>) => onChange({ ...draft, ...p });
  return (
    <Card className={cn(error && "border-danger/60")}>
      <CardContent className="space-y-3 pt-4">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">Reduce (collapse a list → a summary)</span>
          <Button variant="ghost" size="icon" className="size-7" onClick={onRemove}><Trash2 className="size-3.5" /></Button>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Capability id"><Input value={draft.capability_id} onChange={(e) => set({ capability_id: e.target.value })} placeholder="cap.payment.any_hit" className="font-mono text-xs" /></Field>
          <Field label="Op">
            <select className={selectCls} value={draft.op} onChange={(e) => set({ op: e.target.value })}>{REDUCE_OPS.map((o) => <option key={o}>{o}</option>)}</select>
          </Field>
          <Field label="Reads list artifact"><ArtifactKeyInput value={draft.input_artifact_key} onChange={(v) => set({ input_artifact_key: v })} keys={artifactKeys} placeholder="art.payment.screening_list" /></Field>
          <Field label="Summary artifact key"><Input value={draft.output_artifact_key} onChange={(e) => set({ output_artifact_key: e.target.value })} placeholder="art.payment.any_hit_summary" className="font-mono text-xs" /></Field>
          <Field label="Item path"><Input value={draft.item_path} onChange={(e) => set({ item_path: e.target.value })} placeholder="status" className="font-mono text-xs" /></Field>
          <Field label="Output field"><Input value={draft.output_field} onChange={(e) => set({ output_field: e.target.value })} placeholder="has_hit" className="font-mono text-xs" /></Field>
          {PREDICATE_OPS.has(draft.op) && (
            <Field label="Predicate (unary test)" className="col-span-2"><Input value={draft.predicate} onChange={(e) => set({ predicate: e.target.value })} placeholder='"hit"' className="font-mono text-xs" /></Field>
          )}
        </div>
        {error && <p className="text-xs text-danger">{error}</p>}
      </CardContent>
    </Card>
  );
}

// Batch-1 UX: reuse a catalog capability ON DEMAND — a search dialog that queries only once the operator
// types, instead of eager-loading the whole active catalog on step entry (does not scale).
function ReuseSearchDialog({ reused, onToggle }: { reused: string[]; onToggle: (ref: string) => void }) {
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => { const t = setTimeout(() => setDebounced(term), 200); return () => clearTimeout(t); }, [term]);
  const { data: results, isFetching } = useCapabilitySearch(debounced);
  const active = debounced.trim().length > 0;
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm"><Search className="mr-1 size-4" />Reuse a capability</Button>
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>Reuse a capability</DialogTitle></DialogHeader>
        <Input autoFocus value={term} onChange={(e) => setTerm(e.target.value)} placeholder="search the active catalog by id or title…" className="font-mono text-xs" />
        <div className="max-h-80 space-y-1 overflow-y-auto">
          {!active && <p className="py-2 text-xs text-muted-foreground">Type to search — the catalog is queried on demand, not pre-loaded.</p>}
          {active && isFetching && <p className="py-2 text-xs text-muted-foreground">Searching…</p>}
          {(results ?? []).map((c: any) => {
            const ref = `${c.capability_id}@^${c.version}`;
            const on = reused.includes(ref);
            return (
              <button key={ref} onClick={() => onToggle(ref)}
                className={cn("flex w-full items-center gap-3 rounded-md border p-2 text-left", on ? "border-agent" : "border-border")}>
                <input type="checkbox" readOnly checked={on} />
                <span className="flex-1 font-mono text-xs">{ref}</span>
                <Badge variant="outline" className="text-[10px]">{c.kind}</Badge>
                <Badge variant={c.side_effect === "side_effectful" ? "process" : "artifact"} className="text-[10px]">{c.side_effect}</Badge>
              </button>
            );
          })}
          {active && !isFetching && (results ?? []).length === 0 && <p className="py-2 text-xs text-muted-foreground">No matches.</p>}
          {(results ?? []).length >= 20 && <p className="py-1 text-xs text-muted-foreground">Showing the first 20 — refine your search to narrow.</p>}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function CapabilitiesStep({ session, onDone }: { session: OnboardingSession; onDone: (s: OnboardingSession) => void }) {
  const [endpoint, setEndpoint] = useState("");
  const [transport, setTransport] = useState("streamable_http");
  const [introspecting, setIntrospecting] = useState(false);
  const [drafts, setDrafts] = useState<ToolDraft[]>([]);
  const [reused, setReused] = useState<string[]>(session.reused_capability_refs);
  const [busy, setBusy] = useState(false);
  const endpointRef = useRef<HTMLInputElement>(null);
  const toggleReuse = (ref: string) => setReused((r) => r.includes(ref) ? r.filter((x) => x !== ref) : [...r, ref]);
  // ADR-046 (Track 2): inline-authored decision / reduce capabilities + their per-capability errors.
  const [decisions, setDecisions] = useState<DecisionDraft[]>([]);
  const [reduces, setReduces] = useState<ReduceDraft[]>([]);
  const [authorErrs, setAuthorErrs] = useState<Record<string, string>>({});
  // artifact keys the operator can point a decision/reduce input at (staged so far + reused catalog).
  const artifactKeys = useMemo(() => Array.from(new Set([
    ...session.staged_artifacts.map((a) => a.artifact_key),
    ...drafts.filter((d) => d.selected).map((d) => d.output_artifact_key).filter(Boolean),
    ...(session.inferred?.artifact_seeds ?? []).map((a) => a.suggested_artifact_key),
  ])), [session.staged_artifacts, session.inferred, drafts]);
  // ADR-045 (Track 3): split inferred capability candidates — task slots (the "expects capabilities"
  // card) vs external message-flow slots (actionable "external integrations" nudges below).
  const capCandBySource = useMemo(
    () => Object.fromEntries((session.inferred?.capability_candidates ?? []).map((c) => [c.source, c.suggested_capability_id])),
    [session.inferred],
  );
  const mfIds = useMemo(() => new Set((session.bpmn?.message_flows ?? []).map((m) => m.id)), [session.bpmn]);
  const taskCandidates = useMemo(
    () => (session.inferred?.capability_candidates ?? []).filter((c) => !mfIds.has(c.source)),
    [session.inferred, mfIds],
  );
  const externalSlots = useMemo(
    () => (session.bpmn?.message_flows ?? []).map((mf) => ({ id: mf.id, name: mf.name ?? mf.id, cap: capCandBySource[mf.id] as string | undefined })),
    [session.bpmn, capCandBySource],
  );
  // ADR-046: the Track-3 "decision table candidate" (a businessRuleTask) → a one-click authoring action.
  const decisionCandidates = useMemo(
    () => (session.inferred?.annotations ?? [])
      .filter((a) => a.code === "decision_capability_candidate" && a.element_id)
      .map((a) => ({ element_id: a.element_id!, suggestedId: (capCandBySource[a.element_id!] as string | undefined)?.split("@")[0] ?? `cap.${session.basics.default_domain}.${a.element_id}` })),
    [session.inferred, capCandBySource, session.basics.default_domain],
  );

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
    setBusy(true); setAuthorErrs({});
    try {
      const tools: CapabilityToolSelection[] = drafts.filter((d) => d.selected && d.compliance.compliant).map((d) => ({
        tool: d.name, endpoint, transport, domain: session.basics.default_domain,
        input_artifact_key: d.input_artifact_key, output_artifact_key: d.output_artifact_key,
        capability_id: d.capability_id, side_effect: d.side_effect, idempotent: d.idempotent,
        artifact_version: "1.0.0", capability_version: "1.0.0",
        input_schema: d.input_schema ?? undefined, output_schema: d.output_schema ?? undefined,
      }));
      onDone(await setOnboardingCapabilities(session.session_id, {
        tools, reused_capability_refs: reused,
        decision_specs: decisions.map(decisionToSpec), reduce_specs: reduces.map(reduceToSpec),
      }));
    } catch (e) {
      const x = extractErrors(e);
      // ADR-046: surface each authored capability's dmn_*/reduce_* validation error inline (by id).
      const map: Record<string, string> = {};
      x.fields.forEach((f: any) => { if (f.capability_id) map[f.capability_id] = (map[f.capability_id] ? map[f.capability_id] + "; " : "") + f.message; });
      setAuthorErrs(map);
      toast.error(x.fields.map((f) => `${f.field}: ${f.message}`).join("; ") || x.general);
    } finally { setBusy(false); }
  }

  const patch = (name: string, p: Partial<ToolDraft>) => setDrafts((ds) => ds.map((d) => d.name === name ? { ...d, ...p } : d));
  const stagedCount = drafts.filter((d) => d.selected && d.compliance.compliant).length;

  return (
    <div className="space-y-4">
      {taskCandidates.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="flex items-center gap-1.5 text-sm"><Boxes className="size-4 text-agent" /> Your diagram expects capabilities here</CardTitle></CardHeader>
          <CardContent className="space-y-1.5">
            <p className="text-xs text-muted-foreground">Introspect an MCP server or reuse a catalog capability for each. Inference suggests the id; the endpoint + schemas come from introspection.</p>
            <div className="flex flex-wrap gap-1.5">
              {taskCandidates.map((c, i) => (
                <Badge key={i} variant="outline" className="font-mono text-[10px]" title={`from ${c.source}`}>{c.suggested_capability_id}</Badge>
              ))}
            </div>
            {(session.inferred?.artifact_seeds?.length ?? 0) > 0 && (
              <p className="pt-1 text-xs text-muted-foreground">Artifact seeds: {session.inferred!.artifact_seeds.map((a) => a.suggested_artifact_key).join(", ")}</p>
            )}
          </CardContent>
        </Card>
      )}

      {/* ADR-045 (Track 3): external-system message flows → actionable capability-slot nudges. */}
      {externalSlots.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="flex items-center gap-1.5 text-sm"><ShieldAlert className="size-4 text-process" /> External integrations</CardTitle></CardHeader>
          <CardContent className="space-y-1.5">
            <p className="text-xs text-muted-foreground">Each message flow to an external system likely needs its own capability — introspect the provider's MCP server or reuse a catalog capability.</p>
            {externalSlots.map((s) => (
              <div key={s.id} className="flex flex-wrap items-center gap-2 rounded-md border border-border p-2">
                <span className="text-xs font-medium">{s.name}</span>
                {s.cap && <Badge variant="outline" className="font-mono text-[10px]" title={`from message flow ${s.id}`}>→ likely {s.cap}</Badge>}
                <div className="flex-1" />
                <Button variant="outline" size="sm" onClick={() => { endpointRef.current?.focus(); endpointRef.current?.scrollIntoView({ block: "center" }); toast.info(`Introspect the ${s.name} MCP server, then map its tool to ${s.cap ?? "a capability"}.`); }}>Introspect for this</Button>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
      <Card>
        <CardHeader><CardTitle>Create capabilities from an MCP server</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">Point at a running MCP server. Each compliant tool becomes an input artifact, an output artifact, and one <span className="font-mono">mcp</span> capability. Capability creation here is MCP-only; other kinds are reuse-only.</p>
          <div className="flex items-end gap-2">
            <div className="flex-1">
              <Label>MCP server URL</Label>
              <Input ref={endpointRef} value={endpoint} onChange={(e) => setEndpoint(e.target.value)} placeholder="http://wirefix-mcp:8060/mcp" />
              <p className="mt-1 text-xs text-muted-foreground">Use the <span className="font-medium">deployment-facing</span> URL (e.g. the Docker service alias like <span className="font-mono">http://wirefix-mcp:8060/mcp</span>) — <span className="font-medium">not</span> <span className="font-mono">localhost</span>. The registry connects from inside its container, so localhost reaches the container itself, not your host (that URL only works for MCP Inspector).</p>
            </div>
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
                      {(d.compliance.reasons ?? []).join("; ")} · see the MCP Implementor Guideline.
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

      {/* ADR-046 (Track 2): author decision / reduce capabilities inline — no MCP server, no code. */}
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div>
            <CardTitle>Author a decision / reduce (no code)</CardTitle>
            <p className="text-xs text-muted-foreground">A native-DMN <span className="font-mono">decision</span> table (a businessRuleTask) or a <span className="font-mono">reduce</span> over a list — validated live by the platform's DMN/reduce checks.</p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setDecisions((d) => [...d, newDecision()])}><Plus className="mr-1 size-3" />Decision table</Button>
            <Button variant="outline" size="sm" onClick={() => setReduces((r) => [...r, { capability_id: "", input_artifact_key: "", output_artifact_key: "", op: "any", source: "", item_path: "", predicate: "", output_field: "result" }])}><Plus className="mr-1 size-3" />Reduce</Button>
          </div>
        </CardHeader>
        {decisionCandidates.length > 0 && (
          <CardContent className="space-y-1.5 border-b border-border pb-3">
            <p className="text-xs text-muted-foreground">Suggested from your diagram — one click pre-fills a table for that business rule task:</p>
            <div className="flex flex-wrap gap-1.5">
              {decisionCandidates.map((c) => (
                <Button key={c.element_id} variant="outline" size="sm"
                  onClick={() => setDecisions((d) => [...d, newDecision(c.suggestedId)])}>
                  author decision table for {c.element_id}
                </Button>
              ))}
            </div>
          </CardContent>
        )}
        {(decisions.length > 0 || reduces.length > 0) && (
          <CardContent className="space-y-3">
            {decisions.map((d, i) => (
              <DecisionBuilder key={"d" + i} draft={d} artifactKeys={artifactKeys} error={authorErrs[d.capability_id]}
                onChange={(nd) => setDecisions((ds) => ds.map((x, j) => j === i ? nd : x))}
                onRemove={() => setDecisions((ds) => ds.filter((_, j) => j !== i))} />
            ))}
            {reduces.map((r, i) => (
              <ReduceBuilder key={"r" + i} draft={r} artifactKeys={artifactKeys} error={authorErrs[r.capability_id]}
                onChange={(nr) => setReduces((rs) => rs.map((x, j) => j === i ? nr : x))}
                onRemove={() => setReduces((rs) => rs.filter((_, j) => j !== i))} />
            ))}
          </CardContent>
        )}
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div>
            <CardTitle>Reuse existing capabilities</CardTitle>
            <p className="text-xs text-muted-foreground">Search the active catalog on demand — reuse an already-registered capability instead of authoring a new one.</p>
          </div>
          <ReuseSearchDialog reused={reused} onToggle={toggleReuse} />
        </CardHeader>
        {reused.length > 0 && (
          <CardContent className="flex flex-wrap gap-1.5">
            {reused.map((ref) => (
              <Badge key={ref} variant="agent" className="gap-1 font-mono text-[10px]">
                {ref}
                <button onClick={() => toggleReuse(ref)} title="remove" className="ml-0.5 hover:text-danger"><XCircle className="size-3" /></button>
              </Badge>
            ))}
          </CardContent>
        )}
      </Card>

      <StepFooter
        summary={`${stagedCount} MCP · ${decisions.length} decision · ${reduces.length} reduce · ${reused.length} reused`}
        busy={busy} disabled={stagedCount + decisions.length + reduces.length + reused.length === 0} onNext={submit}
      />
    </div>
  );
}

// -- Step 4: bindings ----------------------------------------------------------
// ADR-044 (Track 1): a compact key→value map editor for a call executor's input_map / output_map.
function MapEditor({ value, onChange, keyPlaceholder, valPlaceholder }: {
  value: Record<string, string>; onChange: (m: Record<string, string>) => void;
  keyPlaceholder: string; valPlaceholder: string;
}) {
  const rows = Object.entries(value ?? {});
  const set = (i: number, k: string, v: string) => {
    const next = rows.map(([ek, ev], j) => (j === i ? [k, v] : [ek, ev]) as [string, string]);
    onChange(Object.fromEntries(next.filter(([ek]) => ek)));
  };
  return (
    <div className="space-y-1">
      {rows.map(([k, v], i) => (
        <div key={i} className="flex gap-1">
          <Input value={k} onChange={(e) => set(i, e.target.value, v)} placeholder={keyPlaceholder} className="h-7 font-mono text-[11px]" />
          <Input value={v} onChange={(e) => set(i, k, e.target.value)} placeholder={valPlaceholder} className="h-7 font-mono text-[11px]" />
          <Button variant="ghost" size="icon" className="size-7" onClick={() => onChange(Object.fromEntries(rows.filter((_, j) => j !== i)))}><Trash2 className="size-3" /></Button>
        </div>
      ))}
      <Button variant="outline" size="sm" onClick={() => onChange({ ...value, "": "" })}><Plus className="mr-1 size-3" />mapping</Button>
    </div>
  );
}

// ADR-048: author one input's data source — from the trigger, an upstream task's output, or a composite
// object built field-by-field (recurses). Domain-neutral: names come from the diagram + staged caps.
function SourcePicker({ value, onChange, outputs }: {
  value: any; onChange: (v: any) => void; outputs: { element: string; name: string }[];
}) {
  const mode = value?.fields ? "composite" : (value?.from ?? "trigger");
  const setMode = (m: string) => onChange(
    m === "trigger" ? { from: "trigger" }
      : m === "artifact" ? { from: "artifact", name: outputs[0]?.name ?? "" }
        : { fields: {} });
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1">
        <select className={cn(selectCls, "h-7 w-32 text-[11px]")} value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="trigger">from trigger</option>
          <option value="artifact">upstream output</option>
          <option value="composite">composite</option>
        </select>
        {mode === "artifact" && (
          <select className={cn(selectCls, "h-7 flex-1 text-[11px]")} value={value.name ?? ""} onChange={(e) => onChange({ ...value, name: e.target.value })}>
            <option value="">output…</option>
            {outputs.map((o) => <option key={o.name} value={o.name}>{o.name} ({o.element})</option>)}
          </select>
        )}
        {mode !== "composite" && (
          <Input value={value?.path ?? ""} onChange={(e) => onChange({ ...value, path: e.target.value || undefined })} placeholder="path (opt)" className="h-7 w-24 font-mono text-[11px]" />
        )}
      </div>
      {mode === "composite" && (
        <div className="ml-2 space-y-1 border-l border-border pl-2">
          {Object.entries(value.fields ?? {}).map(([f, sub]: any, i: number) => (
            <div key={i} className="flex items-start gap-1">
              <Input value={f} onChange={(e) => { const fs: any = { ...value.fields }; const v = fs[f]; delete fs[f]; fs[e.target.value] = v; onChange({ fields: fs }); }} placeholder="field" className="h-7 w-24 font-mono text-[11px]" />
              <div className="flex-1"><SourcePicker value={sub} onChange={(nv) => onChange({ fields: { ...value.fields, [f]: nv } })} outputs={outputs} /></div>
              <Button variant="ghost" size="icon" className="size-7" onClick={() => { const fs: any = { ...value.fields }; delete fs[f]; onChange({ fields: fs }); }}><Trash2 className="size-3" /></Button>
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={() => onChange({ fields: { ...value.fields, "": { from: "trigger" } } })}><Plus className="mr-1 size-3" />field</Button>
        </div>
      )}
    </div>
  );
}

function BindingsStep({ session, onDone }: { session: OnboardingSession; onDone: (s: OnboardingSession) => void }) {
  const tasks: OnbBindableElement[] = session.bpmn!.bindable_elements;
  const capOptions = useMemo(
    () => [...session.staged_capabilities.map((c) => `${c.capability_id}@^${c.version}`), ...session.reused_capability_refs],
    [session.staged_capabilities, session.reused_capability_refs],
  );
  const { data: catalog } = useCapabilities();
  const { data: activePacks } = usePacks({ status: "active" });
  const packKeys = useMemo(() => Array.from(new Set((activePacks ?? []).map((p) => p.pack_key))), [activePacks]);
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

  // ADR-027 Phase 1: inferred binding scaffolds pre-fill rows (executor type + lane role + HITL).
  const inferredBind = useMemo(
    () => Object.fromEntries((session.inferred?.bindings ?? []).map((b) => [b.element_id, b])),
    [session.inferred],
  );
  const roleLabelOf = useMemo(
    () => Object.fromEntries((session.inferred?.roles ?? []).map((r) => [r.role_id, r.label])),
    [session.inferred],
  );
  // ADR-045 (Track 3): a businessRuleTask flagged as a decision-table candidate — surfaced with its
  // provenance (Track 2 turns this into "author a table"; here it is a visible affordance).
  const decisionHint = useMemo(
    () => Object.fromEntries((session.inferred?.annotations ?? [])
      .filter((a) => a.code === "decision_capability_candidate" && a.element_id)
      .map((a) => [a.element_id!, a.message])),
    [session.inferred],
  );
  // Batch-2: pre-select each capability task with its inferred capability from the selectable set
  // (staged + reused). Exact bare-id match first, then a CONFIDENT name-token overlap; else leave empty.
  const capByBareId = useMemo(() => Object.fromEntries(capOptions.map((r) => [r.split("@")[0], r])), [capOptions]);
  const suggestedCapRef = useMemo(() => {
    const tok = (s: string) => s.toLowerCase().replace(/^cap\.[a-z0-9_]+\./, "").split(/[^a-z0-9]+/).filter((x) => x && x !== "cap");
    const out: Record<string, string> = {};
    for (const t of tasks) {
      if (t.category !== "capability") continue;
      const sid = inferredBind[t.element_id]?.suggested_capability_id as string | undefined;
      if (sid && capByBareId[sid]) { out[t.element_id] = capByBareId[sid]; continue; }   // exact id
      const want = new Set([...(sid ? tok(sid) : []), ...tok("cap.x." + (t.name ?? ""))]);
      if (want.size === 0 || capOptions.length === 0) continue;
      let best: { ref: string; score: number } | null = null;
      for (const ref of capOptions) {
        const have = tok(ref.split("@")[0] ?? "");
        if (have.length === 0) continue;
        const inter = have.filter((x) => want.has(x)).length;
        const score = inter / new Set([...have, ...want]).size;      // Jaccard over name tokens
        if (!best || score > best.score) best = { ref, score };
      }
      if (best && best.score >= 0.5) out[t.element_id] = best.ref;    // confident match only
    }
    return out;
  }, [tasks, inferredBind, capByBareId, capOptions]);

  // ADR-048: a staged capability's input/output names (single IO) — used to author each capability
  // binding's input_map. bareId → {input, output}.
  const capIO = useMemo(() => {
    const m: Record<string, { input: string; output: string }> = {};
    for (const sc of session.staged_capabilities) m[sc.capability_id] = { input: sc.input_name, output: sc.output_name };
    return m;
  }, [session.staged_capabilities]);
  const ioOf = (ref?: string | null) => (ref ? capIO[ref.split("@")[0] ?? ""] : undefined);

  // ADR-048 D4: a staged capability's input/output NAMES + FIELDS (from the staged artifact schemas the
  // session already ships). The field lists let the wizard build the same field-level input_map the backend
  // does — keyed off the ACTUALLY-BOUND capability, never a name guess (so a task whose BPMN name diverges
  // from its tool id still gets a suggestion). bareId → {input, inFields, output, outFields}.
  const capFields = useMemo(() => {
    const props: Record<string, string[]> = {};
    for (const a of session.staged_artifacts ?? []) {
      const p = (a.json_schema as { properties?: Record<string, unknown> } | undefined)?.properties;
      props[a.artifact_key] = p && typeof p === "object" ? Object.keys(p) : [];
    }
    const m: Record<string, { input: string; inFields: string[]; output: string; outFields: string[] }> = {};
    for (const sc of session.staged_capabilities) {
      m[sc.capability_id] = {
        input: sc.input_name, inFields: props[sc.input_artifact_key] ?? [],
        output: sc.output_name, outFields: props[sc.output_artifact_key] ?? [],
      };
    }
    return m;
  }, [session.staged_capabilities, session.staged_artifacts]);
  const cfOf = (ref?: string | null) => (ref ? capFields[ref.split("@")[0] ?? ""] : undefined);

  // One input field's source: an upstream output that carries the field (→ artifact+path), an upstream
  // output named like the field (→ that whole artifact), else the trigger (opaque client-side, mirroring the
  // backend). Whole-map builder: entry (no upstream) → whole trigger; opaque input → whole nearest output.
  type Up = { name: string; fields: string[] };
  const sourceForField = (f: string, ups: Up[]): Record<string, unknown> => {
    for (const u of ups) {
      if (u.fields.includes(f)) return { from: "artifact", name: u.name, path: f };
      if (f === u.name) return { from: "artifact", name: u.name };
    }
    return { from: "trigger", path: f };
  };
  const buildInputMap = (inName: string, inFields: string[], ups: Up[]): Record<string, unknown> => {
    if (ups.length === 0) return { [inName]: { from: "trigger" } };
    if (inFields.length === 0) return { [inName]: { from: "artifact", name: ups[0]!.name } };
    const fields: Record<string, unknown> = {};
    for (const f of inFields) fields[f] = sourceForField(f, ups);
    return { [inName]: { fields } };
  };
  // Field-level suggestion for a capability element, keyed off its BOUND capability_ref (`refFor` resolves
  // any element's ref — bound row, then pre-selected fallback). Upstream producers come from the BPMN graph
  // (`inferred.upstream_caps`), each resolved to whatever capability that element is bound to.
  const resolveInputSources = (elementId: string, refFor: (id: string) => string | undefined): Record<string, unknown> => {
    const io = cfOf(refFor(elementId));
    if (!io) return {};                                         // reused cap (no client schema) / unbound
    const ups: Up[] = (inferredBind[elementId]?.upstream_caps ?? [])
      .map((up) => { const uio = cfOf(refFor(up)); return uio ? { name: uio.output, fields: uio.outFields } : null; })
      .filter((x): x is Up => x !== null);
    return buildInputMap(io.input, io.inFields, ups);
  };

  // Resolve any element's capability at INIT (rows don't exist yet): its saved binding, else the pre-select.
  const refForInit = (id: string): string | undefined =>
    session.bindings.find((b) => b.element_id === id)?.capability_ref ?? suggestedCapRef[id];

  const [rows, setRows] = useState<Record<string, BindingInput>>(() => {
    const init: Record<string, BindingInput> = {};
    for (const t of tasks) {
      const existing = session.bindings.find((b) => b.element_id === t.element_id);
      const inf = inferredBind[t.element_id];
      const base: BindingInput = {
        element_id: t.element_id, element_kind: t.element_kind,
        executor_type: t.category,     // fixed by the BPMN element kind (capability|human|message|call)
        hitl_mode: existing?.hitl_mode ?? (t.category === "capability" || t.category === "human" ? inf?.suggested_hitl_mode ?? "none" : "none"),
      };
      if (existing) {
        // ADR-048 D4: keep operator-authored input sources; when an existing capability row never got any
        // (empty), fall back to the (now field-level) suggestion so re-opening Bindings still pre-fills.
        const savedSrc = existing.input_sources ?? {};
        Object.assign(base, {
          capability_ref: existing.capability_ref, role: existing.role, hitl_role: existing.hitl_role,
          message_name: existing.message_name, call_pack: existing.call_pack, call_version: existing.call_version,
          input_map: existing.input_map ?? {}, output_map: existing.output_map ?? {},
          input_sources: (t.category === "capability" && Object.keys(savedSrc).length === 0)
            ? resolveInputSources(t.element_id, refForInit) : savedSrc,
        });
      } else {
        if (t.category === "human") {
          // Batch-2: default BOTH the executor role and the HITL role to the lane-derived role, so they
          // read the same (fixing the executor role.payment.* vs HITL role.payments.* mismatch).
          base.role = inf?.suggested_role ?? undefined;
          base.hitl_role = inf?.suggested_role ?? undefined;
        }
        if (t.category === "capability") {
          // Batch-2: pre-select the inferred capability + bump HITL to its floor (mirrors chooseExecutor),
          // so e.g. a side-effectful ApplyRepair shows approve_actions immediately instead of a false none.
          const ref = suggestedCapRef[t.element_id];
          if (ref) {
            base.capability_ref = ref;
            const fl = floorOf(ref);
            if ((HITL_RANK[base.hitl_mode] ?? 0) < fl) base.hitl_mode = fl >= 2 ? "approve_actions" : "review_after";
          }
          if (base.hitl_mode !== "none") base.hitl_role = inf?.suggested_role ?? undefined;
          base.input_sources = resolveInputSources(t.element_id, refForInit);   // ADR-048 D4: pre-fill off the bound cap
        }
        if (t.category === "message") base.message_name = t.message_name ?? undefined;
        if (t.category === "call") { base.call_pack = t.called_pack ?? undefined; base.call_version = t.called_version ?? "^1.0.0"; base.input_map = {}; base.output_map = {}; }
      }
      init[t.element_id] = base;
    }
    return init;
  });
  const [busy, setBusy] = useState(false);
  const [fieldErrs, setFieldErrs] = useState<Record<string, string>>({});

  const patch = (id: string, p: Partial<BindingInput>) => setRows((r) => ({ ...r, [id]: { ...r[id]!, ...p } as BindingInput }));
  // Resolve any element's capability from the LIVE rows (bound row, else the pre-select).
  const refForRows = (id: string): string | undefined => rows[id]?.capability_ref ?? suggestedCapRef[id];
  // Picking a capability bumps HITL to its floor if the current mode is too weak, and RE-DERIVES the input
  // sources for the newly-chosen capability (its input name/fields change with the capability, so the prior
  // sources are stale) — resolving upstream refs with the new choice applied.
  const chooseExecutor = (id: string, ref: string) => {
    const fl = floorOf(ref);
    const cur = rows[id]!.hitl_mode;
    const bumped = (HITL_RANK[cur] ?? 0) < fl ? (fl >= 2 ? "approve_actions" : "review_after") : cur;
    const nextRef = (x: string) => (x === id ? ref : refForRows(x));
    patch(id, { capability_ref: ref, hitl_mode: bumped, input_sources: resolveInputSources(id, nextRef) });
  };

  async function submit() {
    setBusy(true); setFieldErrs({});
    try {
      onDone(await setOnboardingBindings(session.session_id, { bindings: tasks.map((t) => rows[t.element_id]!) }));
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

  // ADR-048: the selectable upstream outputs for an artifact source — every capability task's output.
  const allOutputs = tasks
    .filter((x) => x.category === "capability")
    .map((x) => ({ element: x.element_id, name: ioOf(rows[x.element_id]?.capability_ref)?.output }))
    .filter((o): o is { element: string; name: string } => !!o.name);
  const errorCount = Object.keys(fieldErrs).length;
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">Exactly one binding per bindable element (task kinds, message elements, callActivities). Side-effectful capabilities lock HITL to <span className="font-mono">approve_actions</span> or stricter; message &amp; call executors have no gate.</p>
      {errorCount > 0 && (
        <div className="flex items-center gap-2 rounded-md border border-danger/40 bg-danger-muted/20 p-3 text-sm text-danger">
          <XCircle className="size-4 shrink-0" />
          <span>{errorCount} binding{errorCount === 1 ? "" : "s"} rejected. Fix the highlighted rows below and save again.</span>
        </div>
      )}
      {tasks.map((t) => {
        const id = t.element_id;
        const row = rows[id]!;
        const floor = t.category === "capability" ? floorOf(row.capability_ref) : 0;
        return (
          <Card key={id} className={cn(fieldErrs[id] && "border-danger/60")}>
            <CardContent className="pt-5">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <span className="font-mono text-sm font-medium">{id}</span>
                <Badge variant="outline" className="text-[10px]">{t.element_kind}</Badge>
                <Badge variant="process" className="text-[10px]">{t.category}</Badge>
                <span className="text-xs text-muted-foreground">{t.name}</span>
                {t.is_multi_instance && <Badge variant="artifact" className="text-[10px]" title="Runs N times (multi-instance)">multi-instance</Badge>}
                {t.is_for_compensation && <Badge variant="attention" className="text-[10px]" title={`Undo handler for ${t.compensation_primary}`}>compensates {t.compensation_primary}</Badge>}
                {t.in_event_subprocess && <Badge variant="outline" className="text-[10px]" title="Inside an event sub-process body">event-subprocess</Badge>}
                {t.element_kind === "businessRuleTask" && decisionHint[id] && <Badge variant="process" className="text-[10px]" title={decisionHint[id]}>decision table candidate</Badge>}
                {inferredBind[id]?.suggested_role && (
                  <Badge variant="agent" className="text-[10px]" title="Pre-filled from the BPMN lane — editable">
                    from lane: {roleLabelOf[inferredBind[id]!.suggested_role!] ?? inferredBind[id]!.suggested_role}
                  </Badge>
                )}
              </div>

              {/* Capability / human executors keep the HITL gate; message & call have none. */}
              {(t.category === "capability" || t.category === "human") && (
                <div className="grid grid-cols-3 gap-3">
                  <Field label={t.category === "capability" ? "Capability" : "Role"}>
                    {t.category === "capability" ? (
                      <div className="flex items-center gap-1.5">
                        <select className={cn(selectCls, "flex-1")} value={row.capability_ref ?? ""} onChange={(e) => chooseExecutor(id, e.target.value)}>
                          <option value="">Select…</option>
                          {capOptions.map((r) => <option key={r} value={r}>{r}{sideEffectOf(r) === "side_effectful" ? " · side-effectful" : ""}</option>)}
                        </select>
                        {row.capability_ref && row.capability_ref === suggestedCapRef[id] && (
                          <Badge variant="agent" className="shrink-0 text-[10px]" title="Pre-selected from the diagram — editable">suggested</Badge>
                        )}
                      </div>
                    ) : (
                      <Input value={row.role ?? ""} onChange={(e) => patch(id, { role: e.target.value })} placeholder="role.payments.ops_analyst" className="font-mono text-xs" />
                    )}
                  </Field>
                  <Field label="HITL mode">
                    <select className={selectCls} value={row.hitl_mode} onChange={(e) => patch(id, { hitl_mode: e.target.value })}>
                      {HITL_MODES.map((m) => <option key={m} value={m} disabled={(HITL_RANK[m] ?? 0) < floor}>{m}{(HITL_RANK[m] ?? 0) < floor ? " (too weak)" : ""}</option>)}
                    </select>
                  </Field>
                  <Field label="Role">
                    {row.hitl_mode !== "none"
                      ? <Input value={row.hitl_role ?? ""} onChange={(e) => patch(id, { hitl_role: e.target.value })} placeholder="role.payments.ops_approver" className="font-mono text-xs" />
                      : <p className="py-2 text-xs text-muted-foreground">not required for mode none</p>}
                  </Field>
                </div>
              )}

              {/* ADR-048: input sourcing — where each capability input's data comes from (pre-filled
                  from the diagram; a "suggested" chip marks the inference). */}
              {t.category === "capability" && ioOf(row.capability_ref)?.input && (() => {
                const inName = ioOf(row.capability_ref)!.input;
                const sug = resolveInputSources(id, refForRows)[inName];
                const cur = (row.input_sources ?? {})[inName];
                return (
                  <div className="mt-3 border-t border-border pt-3">
                    <p className="mb-1 text-xs font-medium text-muted-foreground">Input source — where <span className="font-mono">{inName}</span> comes from</p>
                    <div className="flex items-center gap-2">
                      <div className="flex-1">
                        <SourcePicker value={cur ?? { from: "trigger" }}
                          onChange={(v) => patch(id, { input_sources: { ...(row.input_sources ?? {}), [inName]: v } })}
                          outputs={allOutputs.filter((o) => o.element !== id)} />
                      </div>
                      {!!cur && !!sug && JSON.stringify(cur) === JSON.stringify(sug) && (
                        <Badge variant="agent" className="shrink-0 text-[10px]" title="Inferred from the diagram — editable">suggested</Badge>
                      )}
                    </div>
                  </div>
                );
              })()}

              {/* ADR-031 message executor: the awaited business message (no HITL). */}
              {t.category === "message" && (
                <Field label="Message name">
                  <Input value={row.message_name ?? ""} onChange={(e) => patch(id, { message_name: e.target.value })} placeholder="payment.status.reply" className="font-mono text-xs" />
                </Field>
              )}

              {/* ADR-039 call executor: the callee pack + range + IO maps (no HITL of its own). */}
              {t.category === "call" && (
                <div className="space-y-3">
                  <div className="grid grid-cols-2 gap-3">
                    <Field label="Callee pack">
                      <select className={selectCls} value={row.call_pack ?? ""} onChange={(e) => patch(id, { call_pack: e.target.value })}>
                        <option value="">Select active pack…</option>
                        {packKeys.map((k) => <option key={k} value={k}>{k}</option>)}
                      </select>
                    </Field>
                    <Field label="Version range">
                      <Input value={row.call_version ?? "^1.0.0"} onChange={(e) => patch(id, { call_version: e.target.value })} placeholder="^1.0.0" className="font-mono text-xs" />
                    </Field>
                  </div>
                  <Field label="Input map (callee input → caller dotpath)">
                    <MapEditor value={row.input_map ?? {}} onChange={(m) => patch(id, { input_map: m })} keyPlaceholder="callee_input" valPlaceholder="artifacts.x.y" />
                  </Field>
                  <Field label="Output map (caller artifact → callee output)">
                    <MapEditor value={row.output_map ?? {}} onChange={(m) => patch(id, { output_map: m })} keyPlaceholder="caller_artifact" valPlaceholder="callee_output" />
                  </Field>
                </div>
              )}

              {fieldErrs[id] && <p className="mt-2 text-xs text-danger">{fieldErrs[id]}</p>}
            </CardContent>
          </Card>
        );
      })}
      <StepFooter summary={`${tasks.length} element${tasks.length === 1 ? "" : "s"}`} busy={busy} onNext={submit} />
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
      <p className="flex items-start gap-1.5 rounded-md border border-border bg-surface/40 p-3 text-xs text-muted-foreground">
        <Info className="mt-0.5 size-3.5 shrink-0" />
        Triage rules describe which exceptions this pack handles — they match the incoming exception <span className="font-medium">envelope</span>, not the diagram, so they are not derivable from the BPMN. Author at least one below.
      </p>
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
  const tasks = session.bpmn!.bindable_elements.map((e) => e.element_id);   // SoD over the full bindable set
  const artifacts = Array.from(new Set(session.staged_artifacts.map((a) => a.artifact_key)));
  // ADR-027 Phase 1: pre-fill gateway variables from inferred conditions (operator adds source_artifact).
  const inferredGv = Object.fromEntries((session.inferred?.gateway_variables ?? []).map((g) => [g.gateway_id, g.variable]));
  const [gvars, setGvars] = useState<Record<string, { variable: string; source_artifact: string }>>(
    () => Object.fromEntries(gateways.map((g) => {
      const ex = session.gateway_variables.find((v) => v.gateway_id === g);
      return [g, { variable: ex?.variable ?? inferredGv[g] ?? "", source_artifact: ex?.source_artifact ?? "" }];
    })),
  );
  const [sod, setSod] = useState<string[][]>(
    session.sod_policies.length
      ? session.sod_policies.map((s) => s.elements ?? [])
      : (session.inferred?.sod_candidates ?? []).map((c) => c.elements ?? []),
  );
  // ADR-045 (Track 3): the inferred rationale per candidate pair (keyed by its sorted elements) — shown
  // as a "suggested" provenance chip so the operator sees WHY before accepting/removing.
  const sodRationale: Record<string, string> = Object.fromEntries(
    (session.inferred?.sod_candidates ?? []).map((c) => [[...(c.elements ?? [])].sort().join("|"), c.rationale]),
  );
  // Seed roles from bindings + inferred lane roles so the operator can name them here
  // (the backend re-derives the authoritative set from bindings at save time).
  const bindingRoles = [
    ...session.bindings.map((b) => b.hitl_role).filter(Boolean),
    ...session.bindings.filter((b) => b.executor_type === "human").map((b) => b.role).filter(Boolean),
  ] as string[];
  const inferredRoles = (session.inferred?.roles ?? []).map((r) => r.role_id);
  const [roles, setRoles] = useState<string[]>(() => Array.from(new Set([...session.roles, ...bindingRoles, ...inferredRoles])));
  const [roleMeta, setRoleMeta] = useState<Record<string, { label: string; description: string }>>(
    () => {
      const seed: Record<string, { label: string; description: string }> = {};
      // ADR-045 (Track 3): seed each lane persona's inferred description (approver / analyst / agent …),
      // operator-editable; explicit role_meta from the session overrides.
      for (const r of session.inferred?.roles ?? []) seed[r.role_id] = { label: r.label, description: r.description ?? "" };
      for (const [id, m] of Object.entries(session.role_meta ?? {})) seed[id] = { label: m?.label ?? "", description: m?.description ?? "" };
      return seed;
    },
  );
  const [roleInput, setRoleInput] = useState("");
  const [busy, setBusy] = useState(false);

  function metaFor(id: string) {
    return roleMeta[id] ?? { label: "", description: "" };
  }
  function patchMeta(id: string, patch: Partial<{ label: string; description: string }>) {
    setRoleMeta((prev) => ({ ...prev, [id]: { ...metaFor(id), ...patch } }));
  }

  async function submit() {
    setBusy(true);
    try {
      const gateway_variables = gateways
        .filter((g) => gvars[g]!.variable && gvars[g]!.source_artifact)
        .map((g) => ({ gateway_id: g, variable: gvars[g]!.variable, source_artifact: gvars[g]!.source_artifact }));
      // Only send authored metadata (non-empty), keyed by a role still in the list.
      const role_meta = Object.fromEntries(
        roles
          .map((id) => [id, metaFor(id)] as const)
          .filter(([, m]) => m.label.trim() || m.description.trim())
          .map(([id, m]) => [id, { label: m.label.trim() || undefined, description: m.description.trim() || undefined }]),
      );
      onDone(await setOnboardingPolicies(session.session_id, {
        gateway_variables, sod_policies: sod.filter((e) => e.length >= 2).map((elements) => ({ elements })), roles, role_meta,
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
          {sod.map((elements, i) => {
            const rationale = sodRationale[[...elements].sort().join("|")];
            return (
            <div key={i} className="rounded-md border border-border p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs uppercase tracking-wide text-muted-foreground">distinct_actor</span>
                  {rationale && (
                    <Badge variant="agent" className="text-[10px]" title="Inferred from the BPMN lanes — accept or remove">
                      suggested · {rationale}
                    </Badge>
                  )}
                </div>
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
            );
          })}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Pack roles</CardTitle>
          <p className="text-xs text-muted-foreground">
            Name each role a human-friendly label and description — admins see these when granting the
            role. Ids referenced by your bindings are listed automatically; the label/description are
            optional (a humanized fallback is used when blank).
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          {roles.length === 0 && (
            <p className="text-sm text-muted-foreground">No roles yet — add the ids your process uses.</p>
          )}
          {roles.map((r) => (
            <div key={r} className="rounded-md border border-border p-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="font-mono text-xs font-medium">{r}</span>
                <Button variant="ghost" size="icon" className="size-7"
                  onClick={() => setRoles(roles.filter((x) => x !== r))}><XCircle className="size-3.5" /></Button>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Label">
                  <Input value={metaFor(r).label} onChange={(e) => patchMeta(r, { label: e.target.value })}
                    placeholder="Sanctions Analyst" className="text-xs" />
                </Field>
                <Field label="Description">
                  <Input value={metaFor(r).description} onChange={(e) => patchMeta(r, { description: e.target.value })}
                    placeholder="Reviews screening hits" className="text-xs" />
                </Field>
              </div>
            </div>
          ))}
          <Input value={roleInput} onChange={(e) => setRoleInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && roleInput.trim()) { setRoles(Array.from(new Set([...roles, roleInput.trim()]))); setRoleInput(""); } }}
            placeholder="role.payments.ops_approver + Enter" className="w-72 font-mono text-xs" />
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
          <ReadRow label="BPMN · tasks" value={`${session.bpmn?.bpmn_file ?? "—"} · ${session.bpmn?.bindable_elements.length ?? 0} bound`} />
          <ReadRow label="Dependencies" value={`${session.staged_capabilities.length + session.reused_capability_refs.length} caps · ${session.staged_artifacts.length} new artifacts`} />
          <div className="col-span-3 flex items-center gap-2 text-sm">
            <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Execution profile</span>
            <ProfileBadge profile={session.bpmn?.required_execution_profile} />
            {session.bpmn?.required_execution_profile && session.bpmn.required_execution_profile !== "common_subset" && (
              <span className="text-xs text-muted-foreground">— this pack loads only on a runtime at the <span className="font-mono">{session.bpmn.required_execution_profile}</span> profile.</span>
            )}
          </div>
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
