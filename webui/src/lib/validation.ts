import type { ValidationFinding, FindingSeverity } from "@/api/services/registry";

/** Human names for the 7 process-registry validator stages (onboarding wizard grouping). */
export const VALIDATION_STAGES: Record<number, string> = {
  1: "BPMN structure",
  2: "Binding ↔ task bijection",
  3: "Capability resolution",
  4: "HITL & side-effect policy",
  5: "Artifacts & IO",
  6: "Gateway variables",
  7: "Policies & triage",
};

export const SEVERITY_VARIANT: Record<FindingSeverity, "danger" | "attention" | "artifact"> = {
  error: "danger",
  warning: "attention",
  info: "artifact",
};

/** Group findings by their validator stage (1..7), preserving stage order. */
export function groupByStage(findings: ValidationFinding[]): { stage: number; name: string; findings: ValidationFinding[] }[] {
  const byStage = new Map<number, ValidationFinding[]>();
  for (const f of findings) {
    const arr = byStage.get(f.stage) ?? [];
    arr.push(f);
    byStage.set(f.stage, arr);
  }
  return [...byStage.keys()]
    .sort((a, b) => a - b)
    .map((stage) => ({ stage, name: VALIDATION_STAGES[stage] ?? `Stage ${stage}`, findings: byStage.get(stage)! }));
}

export function countBySeverity(findings: ValidationFinding[]): Record<FindingSeverity, number> {
  return findings.reduce(
    (acc, f) => ({ ...acc, [f.severity]: (acc[f.severity] ?? 0) + 1 }),
    { error: 0, warning: 0, info: 0 } as Record<FindingSeverity, number>,
  );
}
