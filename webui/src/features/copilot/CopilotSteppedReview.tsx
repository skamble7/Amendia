// CopilotSteppedReview — ADR-054 Part A. The default post-generate front door: a stepped, PRE-FILLED, editable
// review over the copilot-generated session. It re-composes the SAME wizard step components (now seeded from the
// generated session, not blank) into a business-first order, keeps the plain-language summary + chat-refine panel
// in a persistent rail, and gates go-live on clean validation. Nothing is authored from scratch — copilot
// generates; the operator reviews, tweaks, and approves.
import { useState } from "react";
import { toast } from "sonner";
import { Check } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { type OnboardingSession } from "@/api/services/registry";
import {
  BindingsStep, TriageStep, PoliciesStep,
} from "@/features/registry/OnboardingWizard";
import { CopilotCapabilitiesStep } from "./CopilotCapabilitiesStep";
import { ArtifactsStep } from "./ArtifactsStep";
import { CopilotChat } from "./CopilotChat";
import { CopilotReview } from "./CopilotReview";
import { gatesOf } from "./humanize";

const STEPS = [
  "Understanding", "Capabilities", "Artifacts & schemas", "Bindings", "Gateways", "Trigger & triage", "Review & go live",
] as const;

const BLURBS: Record<number, string> = {
  0: "What the copilot understood from your diagram — the flow, the lanes, and where a person is involved.",
  1: "The tools it connected as automated capabilities. Check the side-effect flags — they set the minimum oversight.",
  2: "Every artifact in the process. Refine each human-authored one so the person filling it sees clean, labeled fields.",
  3: "How each step runs: which tool or person, the oversight level, and where its inputs come from — all pre-filled.",
  4: "Branch conditions and separation-of-duties, read from the diagram’s gateways.",
  5: "The trigger and triage you provided — confirm or adjust which events this process handles.",
  6: "A plain-language summary and the validation report. Approve to go live once everything is clean.",
};

export function CopilotSteppedReview({ session: initial, xml }: { session: OnboardingSession; xml?: string }) {
  const [session, setSession] = useState<OnboardingSession>(initial);
  const [step, setStep] = useState(0);

  const apply = (s: OnboardingSession, next?: number) => {
    setSession(s);
    if (s.last_cleared?.length) toast.info(`Reset downstream: ${s.last_cleared.join(", ").replace(/_/g, " ")}`);
    if (next !== undefined) setStep(next);
  };

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

        {step === 0 && <UnderstandingStep session={session} />}
        {step === 1 && <CopilotCapabilitiesStep session={session} onDone={(s) => apply(s, 2)} />}
        {step === 2 && <ArtifactsStep session={session} onSession={setSession} />}
        {step === 3 && <BindingsStep session={session} onDone={(s) => apply(s, 4)} onSession={setSession} />}
        {step === 4 && <PoliciesStep session={session} onDone={(s) => apply(s, 5)} />}
        {step === 5 && <TriageStep session={session} onDone={(s) => apply(s, 6)} onSession={setSession} />}
        {step === 6 && <CopilotReview session={session} xml={xml} />}
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
function UnderstandingStep({ session }: { session: OnboardingSession }) {
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
    </div>
  );
}
