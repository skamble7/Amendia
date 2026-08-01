// CopilotSteppedReview — ADR-054 Part A. The default post-generate front door: a stepped, PRE-FILLED, editable
// review over the copilot-generated session. It re-composes the SAME wizard step components (now seeded from the
// generated session, not blank) into a business-first order, keeps the plain-language summary + chat-refine panel
// in a persistent rail, and gates go-live on clean validation. Nothing is authored from scratch — copilot
// generates; the operator reviews, tweaks, and approves.
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Check } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  assembleOnboarding, setOnboardingPolicies, setOnboardingTriage, type OnboardingSession,
} from "@/api/services/registry";
import {
  BindingsStep, PoliciesStep, StepFooter,
} from "@/features/registry/OnboardingWizard";
import { CopilotCapabilitiesStep } from "./CopilotCapabilitiesStep";
import { CopilotTriageConfirm } from "./CopilotTriageConfirm";
import { ArtifactsStep } from "./ArtifactsStep";
import { CopilotChat } from "./CopilotChat";
import { CopilotReview } from "./CopilotReview";
import { gatesOf } from "./humanize";

// Order matches the engine's transition chain (bindings → triage → policies → assemble): Trigger & triage precedes
// Gateways, so a forward walk drives the setters in the sequence each guard expects.
const STEPS = [
  "Understanding", "Capabilities", "Artifacts & schemas", "Bindings", "Trigger & triage", "Gateways", "Review & go live",
] as const;

// The onboarding state machine's rank, for deciding what tail to re-drive after an edit regressed the session.
const RANK: Record<string, number> = {
  initiated: 0, bpmn_attached: 1, capabilities_resolved: 2, bindings_set: 3,
  triage_set: 4, policies_set: 5, assembled: 6, completed: 6,
};
const rank = (state: string): number => RANK[state] ?? 0;   // BINDINGS_SET=3 · TRIAGE_SET=4 · POLICIES_SET=5 · ASSEMBLED=6

const BLURBS: Record<number, string> = {
  0: "What the copilot understood from your diagram — the flow, the lanes, and where a person is involved.",
  1: "The tools it connected as automated capabilities. Check the side-effect flags — they set the minimum oversight.",
  2: "Every artifact in the process. Refine each human-authored one so the person filling it sees clean, labeled fields.",
  3: "How each step runs: which tool or person, the oversight level, and where its inputs come from — all pre-filled.",
  4: "The trigger and triage you provided — confirm or adjust which events this process handles.",
  5: "Branch conditions and separation-of-duties, read from the diagram’s gateways.",
  6: "A plain-language summary and the validation report. Approve to go live once everything is clean.",
};

export function CopilotSteppedReview({ session: initial, xml, editMode }: { session: OnboardingSession; xml?: string; editMode?: boolean }) {
  const [session, setSession] = useState<OnboardingSession>(initial);
  const [step, setStep] = useState(0);

  const apply = (s: OnboardingSession, next?: number) => {
    setSession(s);
    if (s.last_cleared?.length) toast.info(`Reset downstream: ${s.last_cleared.join(", ").replace(/_/g, " ")}`);
    if (next !== undefined) setStep(next);
  };

  // Re-establish the tail (triage → policies → assemble) from the current session data when an upstream edit
  // regressed the state, so validation + go-live reflect the edit. A no-op when already ASSEMBLED.
  const ensureAssembled = async (s: OnboardingSession): Promise<OnboardingSession> => {
    if (rank(s.state) < 3) return s;                          // a capabilities-level edit — the Bindings step re-drives it
    const id = s.session_id;
    let cur = s;
    if (rank(cur.state) < 4) cur = await setOnboardingTriage(id, { triage_rules: cur.triage_rules });
    if (rank(cur.state) < 5) cur = await setOnboardingPolicies(id, {
      gateway_variables: cur.gateway_variables, sod_policies: cur.sod_policies, roles: cur.roles, role_meta: cur.role_meta });
    if (rank(cur.state) < 6) cur = await assembleOnboarding(id);
    return cur;
  };

  // A persist step's Continue already ran its own setter (regressing state); re-drive the tail back to ASSEMBLED
  // before advancing so the next step sees a valid session in canonical order. The navigate-only (unedited) path
  // passes an already-ASSEMBLED session → ensureAssembled no-ops (no setter re-invoked).
  const persistStep = async (s: OnboardingSession, next: number) => {
    try { setSession(await ensureAssembled(s)); }
    catch { setSession(s); }                                  // a failed assemble surfaces via the Review report
    setStep(next);
  };

  // Part 3: reaching Review after an edit regressed the state (e.g. via the stepper) → re-assemble deterministically.
  useEffect(() => {
    if (step === 6 && rank(session.state) < 6) {
      ensureAssembled(session).then(setSession).catch(() => { /* surfaced as the validation report */ });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  // The shared Back/Continue footer for the read-mostly steps (Continue just advances; nothing to persist).
  const sharedFooter = (
    <StepFooter summary="" busy={false} nextLabel="Continue"
      onBack={step > 0 ? () => setStep(step - 1) : undefined}
      onNext={() => setStep(step + 1)} />
  );

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
      <div>
        {/* Stepper — every step is reachable; the generated session pre-fills them all. */}
        <div className="mb-5 flex flex-wrap items-center gap-y-2">
          {STEPS.map((label, i) => (
            <div key={label} className="flex items-center">
              <button onClick={() => setStep(i)} className="flex items-center gap-2">
                <span className={cn(
                  "flex size-6 items-center justify-center rounded-full border text-xs",
                  i === step ? "border-agent bg-agent text-agent-foreground"
                    : i < step ? "border-success bg-success text-success-foreground"
                    : "border-border text-muted-foreground",
                )}>
                  {i < step ? <Check className="size-3.5" /> : i + 1}
                </span>
                <span className={cn("text-sm", i === step ? "font-medium" : "text-muted-foreground")}>{label}</span>
              </button>
              {i < STEPS.length - 1 && <span className="mx-2 h-px w-6 bg-border" />}
            </div>
          ))}
        </div>

        <p className="mb-4 text-sm text-muted-foreground">{BLURBS[step]}</p>

        {/* One uniform Back/Continue footer on every step. Read-mostly steps (Understanding/Capabilities/Artifacts/
            Trigger & triage/Review) render this shared footer; the persist steps (Bindings/Gateways) bring the same
            footer wired to their save action, so behavior is preserved with a consistent control. */}
        {step === 0 && <UnderstandingStep session={session} footer={sharedFooter} />}
        {step === 1 && <CopilotCapabilitiesStep session={session} onDone={(s) => apply(s, 2)} footer={sharedFooter} />}
        {step === 2 && <ArtifactsStep session={session} onSession={setSession} footer={sharedFooter} />}
        {step === 3 && <BindingsStep session={session} onDone={(s) => persistStep(s, 4)} onSession={setSession}
                                     onBack={() => setStep(2)} nextLabel="Continue" navigateOnly />}
        {step === 4 && <CopilotTriageConfirm session={session} onSession={setSession} footer={sharedFooter} />}
        {step === 5 && <PoliciesStep session={session} onDone={(s) => persistStep(s, 6)}
                                     onBack={() => setStep(4)} nextLabel="Continue" navigateOnly />}
        {step === 6 && (
          <div className="space-y-4">
            <CopilotReview session={session} xml={xml} editMode={editMode} />
            <StepFooter summary="approve to go live" busy={false} onBack={() => setStep(5)} />
          </div>
        )}
      </div>

      {/* Persistent rail: the plain-language summary + natural-language refine chat stay available on every step. */}
      <aside className="space-y-4 lg:sticky lg:top-4 lg:self-start">
        {session.copilot_report?.summary && (
          <Card>
            <CardHeader><CardTitle className="text-sm">In plain language</CardTitle></CardHeader>
            <CardContent className="text-sm text-muted-foreground">{session.copilot_report.summary}</CardContent>
          </Card>
        )}
        <CopilotChat session={session} onUpdated={setSession} />
      </aside>
    </div>
  );
}

// Step 0 — read-mostly: the copilot's understanding (inferred lanes→roles + the human-involvement gates). The
// plain-language summary lives in the persistent rail, so it isn't duplicated here.
function UnderstandingStep({ session, footer }: { session: OnboardingSession; footer?: React.ReactNode }) {
  const roles = session.inferred?.roles ?? [];
  const gates = gatesOf(session);
  return (
    <div className="space-y-4">
      {roles.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-sm">Roles (from the diagram lanes)</CardTitle></CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {roles.map((r) => (
              <Badge key={r.role_id} variant="outline">{r.label}<span className="ml-1 font-mono text-[10px] opacity-70">{r.role_id}</span></Badge>
            ))}
          </CardContent>
        </Card>
      )}
      {gates.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-sm">Where a person is involved</CardTitle></CardHeader>
          <CardContent className="space-y-1">
            {gates.map((g) => (
              <p key={g.elementId} className="text-sm text-muted-foreground">
                {g.sentence}{g.authorize && <Badge variant="outline" className="ml-2">authorize</Badge>}
              </p>
            ))}
          </CardContent>
        </Card>
      )}
      {footer}
    </div>
  );
}
