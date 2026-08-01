// features/copilot/CopilotReview.tsx — the plain-language design sign-off. Everything renders from
// copilot_report + the (humanized) bindings; no JSON, no schema_refs, no raw HITL modes, no Task_* ids.
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, ShieldCheck, HelpCircle, Rocket, Settings2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BpmnViewer } from "@/features/registry/BpmnViewer";
import { commitOnboarding, type OnboardingSession } from "@/api/services/registry";
import { gatesOf, readinessOf } from "./humanize";

export function CopilotReview({ session, xml }: { session: OnboardingSession; xml?: string }) {
  const [activated, setActivated] = useState<string | null>(session.result_pack ?? null);
  const gates = gatesOf(session);
  const readiness = readinessOf(session);
  const report = session.copilot_report;
  const openQuestions = report?.open_questions ?? [];

  const activate = useMutation({
    mutationFn: () => commitOnboarding(session.session_id),
    onSuccess: (s) => {
      if (s.state === "completed" && s.result_pack) {
        setActivated(s.result_pack);
        toast.success(`${s.result_pack} is live — it now handles matching work.`);
      }
    },
    onError: () => toast.error("Couldn't go live. See readiness below or the technical detail."),
  });

  if (activated) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center py-14 text-center">
          <div className="mb-4 flex size-14 items-center justify-center rounded-2xl bg-success-muted text-success">
            <Rocket className="size-7" />
          </div>
          <h2 className="text-xl font-medium">Your process is live</h2>
          <p className="mt-2 max-w-md text-sm text-muted-foreground">
            <span className="font-medium text-foreground">{session.basics.title}</span> is now running and will pick
            up matching work automatically.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      {/* Summary */}
      <Card>
        <CardContent className="pt-5">
          <h2 className="text-lg font-medium">{session.basics.title}</h2>
          <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-muted-foreground">
            {report?.summary || "The copilot has drafted this process from your diagram and tools."}
          </p>
        </CardContent>
      </Card>

      {/* Gates at a glance */}
      <Card>
        <CardContent className="pt-5">
          <h3 className="mb-2 flex items-center gap-2 text-sm font-medium"><ShieldCheck className="size-4 text-muted-foreground" /> Where a person is involved</h3>
          {gates.length === 0 ? (
            <p className="text-sm text-muted-foreground">This process runs fully automatically — no human steps.</p>
          ) : (
            <ul className="space-y-1.5">
              {gates.map((g) => (
                <li key={g.elementId} className="flex items-start gap-2 text-sm">
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-agent" />
                  <span>{g.sentence}</span>
                  {g.authorize && <Badge variant="attention" className="text-[10px]">authorizes a real-world action</Badge>}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* Open questions */}
      {openQuestions.length > 0 && (
        <Card>
          <CardContent className="pt-5">
            <h3 className="mb-2 flex items-center gap-2 text-sm font-medium"><HelpCircle className="size-4 text-muted-foreground" /> The copilot would like you to confirm</h3>
            <ul className="space-y-1.5">
              {openQuestions.map((q, i) => (
                <li key={i} className="text-sm text-muted-foreground">• {q.question}</li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-muted-foreground">Answer these in the chat on the right — the copilot will adjust the design.</p>
          </CardContent>
        </Card>
      )}

      {/* Diagram */}
      {xml && (
        <Card>
          <CardContent className="pt-5">
            <h3 className="mb-2 text-sm font-medium">Your process diagram</h3>
            <div className="h-[32rem] overflow-hidden rounded-md border border-border">
              <BpmnViewer xml={xml} className="h-full" controls />
            </div>
          </CardContent>
        </Card>
      )}

      {/* Readiness + actions */}
      <Card className={readiness.ready ? "border-success/40" : "border-danger/40"}>
        <CardContent className="pt-5">
          {readiness.ready ? (
            <div className="flex items-center gap-2 text-sm font-medium text-success">
              <CheckCircle2 className="size-4" /> Ready to go live
            </div>
          ) : (
            <div>
              <div className="flex items-center gap-2 text-sm font-medium text-danger">
                <XCircle className="size-4" /> Not ready to go live yet
              </div>
              <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
                {readiness.issues.map((m, i) => <li key={i}>• {m}</li>)}
              </ul>
              <p className="mt-2 text-xs text-muted-foreground">Ask the copilot to fix these in the chat, or open the technical detail for specifics.</p>
            </div>
          )}

          <div className="mt-4 flex items-center justify-between gap-3">
            <Button variant="success" disabled={!readiness.ready || activate.isPending} onClick={() => activate.mutate()}>
              <Rocket className="size-4" /> Approve &amp; go live
            </Button>
            <Link to={`/registry/onboard/technical/${session.session_id}`}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
              <Settings2 className="size-3.5" /> View / edit technical detail
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
