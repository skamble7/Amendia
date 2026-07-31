// CopilotTriageConfirm — ADR-054/copilot Part B. Trigger + triage are collected at the Start screen (they're
// required BEFORE generate). Re-rendering the full builder in the stepped review reads as re-entering what's done,
// so this step is a read-mostly CONFIRMATION: the declared trigger + field count and each triage rule in plain
// form, with an Edit affordance that reveals the builder only if the operator wants to change something.
import { useState } from "react";
import { Pencil } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { TriageStep } from "@/features/registry/OnboardingWizard";
import { type OnboardingSession } from "@/api/services/registry";

/** A triage predicate tree → a plain one-line phrase, e.g. "exception_type eq unable_to_apply". */
function describeWhen(when: Record<string, unknown> | undefined | null): string {
  if (!when || typeof when !== "object") return "—";
  for (const junction of ["all", "any"] as const) {
    if (junction in when) {
      const subs = (when[junction] as Record<string, unknown>[]) ?? [];
      return subs.map(describeWhen).join(junction === "all" ? " AND " : " OR ") || "—";
    }
  }
  if ("not" in when) return `NOT ${describeWhen(when.not as Record<string, unknown>)}`;
  const { field, op, value } = when as { field?: string; op?: string; value?: unknown };
  if (field && op) {
    const v = value === undefined ? "" : typeof value === "string" ? value : JSON.stringify(value);
    return `${field} ${op}${v ? ` ${v}` : ""}`;
  }
  return JSON.stringify(when);
}

export function CopilotTriageConfirm({ session, onSession, footer }: {
  session: OnboardingSession;
  onSession: (s: OnboardingSession) => void;
  footer?: React.ReactNode;
}) {
  const [editing, setEditing] = useState(false);

  if (editing) {
    // reveal the full builder only on demand; saving returns to the confirmation with the updated draft
    return <TriageStep session={session} onSession={onSession} onDone={(s) => { setEditing(false); onSession(s); }} />;
  }

  const trig = session.trigger_artifact;
  const props = (trig?.json_schema as { properties?: Record<string, unknown> } | undefined)?.properties ?? {};
  const fieldCount = Object.keys(props).length;
  const rules = session.triage_rules ?? [];

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle className="text-sm">Trigger &amp; triage — confirm what you entered at Start</CardTitle>
          <Button variant="outline" size="sm" className="gap-1" onClick={() => setEditing(true)}>
            <Pencil className="size-3.5" /> Edit
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <p className="text-xs font-medium text-muted-foreground">Trigger</p>
            <p className="text-sm">
              {trig ? `${trig.artifact_key} · ${fieldCount} field${fieldCount === 1 ? "" : "s"}` : "No trigger declared."}
            </p>
          </div>
          <div>
            <p className="text-xs font-medium text-muted-foreground">Triage rules</p>
            {rules.length === 0 ? (
              <p className="text-sm text-muted-foreground">No triage rules.</p>
            ) : (
              <ul className="space-y-1">
                {rules.map((r) => <li key={r.rule_id} className="font-mono text-sm">{describeWhen(r.when as Record<string, unknown>)}</li>)}
              </ul>
            )}
          </div>
        </CardContent>
      </Card>
      {footer}
    </div>
  );
}
