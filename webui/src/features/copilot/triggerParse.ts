// features/copilot/triggerParse.ts — parse the user's pasted trigger (a JSON Schema OR a sample event) into a
// flat {field → jsonType} map so the triage builder can offer the real trigger fields. Mirrors the backend's
// resolve_trigger_schema heuristic (domain-neutral).

export function looksLikeSchema(raw: Record<string, unknown>): boolean {
  if ("$schema" in raw || "properties" in raw) return true;
  const t = raw.type;
  return (t === "object" || t === "array" || t === "string" || t === "number" || t === "integer" || t === "boolean")
    && Object.keys(raw).length <= 2;
}

function jsType(v: unknown): string {
  if (typeof v === "boolean") return "boolean";
  if (typeof v === "number") return Number.isInteger(v) ? "integer" : "number";
  if (typeof v === "string") return "string";
  if (Array.isArray(v)) return "array";
  if (v && typeof v === "object") return "object";
  return "string";
}

/** The top-level fields of the trigger, mapped to their JSON type (for the triage field picker + op filtering). */
export function parseTriggerFields(raw: Record<string, unknown>): Record<string, string> {
  const out: Record<string, string> = {};
  if (looksLikeSchema(raw)) {
    const props = (raw.properties ?? {}) as Record<string, { type?: string | string[] }>;
    for (const [k, v] of Object.entries(props)) {
      const t = Array.isArray(v?.type) ? v.type.find((x) => x !== "null") : v?.type;
      out[k] = (t as string) ?? "string";
    }
  } else {
    for (const [k, v] of Object.entries(raw)) out[k] = jsType(v);
  }
  return out;
}
