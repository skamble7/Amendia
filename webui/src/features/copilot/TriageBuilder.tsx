// features/copilot/TriageBuilder.tsx — "Which incoming events this process handles". A manual predicate builder
// over the trigger's parsed fields, producing the same {field, op, value} predicate shape the wizard/backend use
// (lib/predicate). Each row is one triage rule; the field picker offers the parsed trigger fields. Feeds
// generate.triage_rules. Business-framed but exact — the operator owns routing (it is never inferred).
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { opsForType, defaultOpForType, leafPredicate } from "@/lib/predicate";

const selectCls = "h-8 rounded-md border border-border bg-background px-2 text-xs";

export interface TriageRuleDraft {
  rule_id: string;
  field: string;
  op: string;
  value: string;
}

export function newRule(fields: Record<string, string>): TriageRuleDraft {
  const field = Object.keys(fields)[0] ?? "";
  return { rule_id: "", field, op: defaultOpForType(fields[field]), value: "" };
}

/** Build the backend triage_rules payload from the drafts (only fully-specified rows). */
export function toTriageRules(drafts: TriageRuleDraft[], fields: Record<string, string>) {
  return drafts
    .filter((d) => d.field && d.op)
    .map((d, i) => ({
      rule_id: (d.rule_id || "").trim() || `rule_${i + 1}`,
      priority: 100,
      when: leafPredicate(d.field, d.op, d.value, fields[d.field]),
    }));
}

export function TriageBuilder({ fields, rules, onChange }: {
  fields: Record<string, string>;
  rules: TriageRuleDraft[];
  onChange: (rules: TriageRuleDraft[]) => void;
}) {
  const fieldNames = Object.keys(fields);
  const set = (i: number, p: Partial<TriageRuleDraft>) => onChange(rules.map((r, j) => (j === i ? { ...r, ...p } : r)));
  const add = () => onChange([...rules, newRule(fields)]);
  const rm = (i: number) => onChange(rules.filter((_, j) => j !== i));

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <h3 className="text-sm font-medium">Which incoming events this process handles</h3>
        <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={add} disabled={fieldNames.length === 0}>
          <Plus className="mr-1 size-3" /> Add rule
        </Button>
      </div>
      <p className="mb-2 text-xs text-muted-foreground">
        Route an event here when its fields match — e.g. when its type equals the one this process handles.
      </p>
      {fieldNames.length === 0 ? (
        <p className="text-xs text-muted-foreground">Paste the starting event above first — then pick its fields here.</p>
      ) : rules.length === 0 ? (
        <p className="text-xs text-muted-foreground">No rules yet — add at least one so the process knows what to handle.</p>
      ) : (
        <div className="space-y-2">
          {rules.map((r, i) => {
            const ops = opsForType(fields[r.field]);
            return (
              <div key={i} className="flex flex-wrap items-center gap-1.5">
                <select className={cn(selectCls, "w-36")} value={r.field}
                  onChange={(e) => set(i, { field: e.target.value, op: defaultOpForType(fields[e.target.value]) })}
                  aria-label="Trigger field">
                  {fieldNames.map((f) => <option key={f} value={f}>{f}</option>)}
                </select>
                <select className={cn(selectCls, "w-28")} value={r.op} onChange={(e) => set(i, { op: e.target.value })}
                  aria-label="Operator">
                  {ops.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
                {r.op !== "exists" && (
                  <Input value={r.value} onChange={(e) => set(i, { value: e.target.value })}
                    placeholder={r.op === "in" || r.op === "intersects" ? "a, b, c" : "value"}
                    className="h-8 w-40 font-mono text-xs" aria-label="Value" />
                )}
                <Button variant="ghost" size="icon" className="size-8" onClick={() => rm(i)} aria-label="Remove rule">
                  <Trash2 className="size-3.5" />
                </Button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
