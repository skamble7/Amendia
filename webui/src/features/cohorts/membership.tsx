import { Input } from "@/components/ui/input";
import { useTriggerFields } from "./queries";
import type { CohortDefinition, ProcessPackManifest } from "@/api/types";

/**
 * The correlation-key control shared by the New-cohort form (staged) and the Definition-detail members editor
 * (live). Renders a select over the pack's declared trigger fields (`getTriggerFields`), or a free dotpath input
 * when the pack declares none. Presentation only — the caller owns the value + what happens onChange.
 */
export function CorrelationKeySelect({
  packKey,
  version,
  value,
  onChange,
  className,
  ariaLabel,
}: {
  packKey: string;
  version: string;
  value: string;
  onChange: (key: string) => void;
  className?: string;
  ariaLabel?: string;
}) {
  const { data: fields } = useTriggerFields(packKey, version);
  const hasFields = (fields?.length ?? 0) > 0;
  if (hasFields) {
    return (
      <select
        aria-label={ariaLabel}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`h-8 rounded-md border border-input bg-transparent px-2 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${className ?? ""}`}
      >
        <option value="" disabled>select field…</option>
        {fields!.map((f) => <option key={f} value={f}>{f}</option>)}
      </select>
    );
  }
  return (
    <Input
      aria-label={ariaLabel}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder="dotpath e.g. exception_id"
      className={`h-8 w-40 font-mono text-xs ${className ?? ""}`}
    />
  );
}

/** A definition's members = active packs whose cohort_membership points at it. */
export function membersOf(def: CohortDefinition, packs: ProcessPackManifest[] | undefined): ProcessPackManifest[] {
  return (packs ?? []).filter((p) => p.cohort_membership?.cohort_def_id === def.cohort_def_id);
}

/** Active packs not assigned to ANY cohort (the "+ Add pack" candidates). */
export function unassignedPacks(packs: ProcessPackManifest[] | undefined): ProcessPackManifest[] {
  return (packs ?? []).filter((p) => !p.cohort_membership);
}

/** "event=process_completed → case_id" — the close-schema recognition summary for the definitions table. */
export function closeMatch(def: CohortDefinition): string {
  const props = (def.close_schema?.properties ?? {}) as Record<string, { const?: unknown }>;
  const ev = props.event?.const;
  const left = ev != null ? `event=${String(ev)}` : "close schema";
  return `${left} → ${def.close_correlation_path}`;
}
