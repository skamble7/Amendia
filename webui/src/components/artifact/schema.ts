/**
 * Minimal JSON Schema helpers for the artifact renderer. Artifact schemas are
 * simple by platform convention: a root object, draft 2020-12,
 * additionalProperties:false, no external $refs. We only support what those
 * schemas use (object / array / string+enum / number / integer / boolean).
 */
export interface JsonSchema {
  type?: string | string[];
  title?: string;
  description?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  enum?: unknown[];
  format?: string;
  minimum?: number;
  maximum?: number;
  additionalProperties?: boolean | JsonSchema;
  $id?: string;
  [k: string]: unknown;
}

/** Parse a pinned artifact ref `art.x.y@1.2.3` into its key + version. */
export function parsePinnedRef(ref: string): { key: string; version: string } | null {
  const at = ref.indexOf("@");
  if (at < 0) return null;
  return { key: ref.slice(0, at), version: ref.slice(at + 1) };
}

export function schemaType(schema: JsonSchema | undefined): string {
  if (!schema) return "unknown";
  const t = Array.isArray(schema.type) ? schema.type.find((x) => x !== "null") : schema.type;
  if (t) return t;
  if (schema.enum) return "string";
  if (schema.properties) return "object";
  if (schema.items) return "array";
  return "unknown";
}

/** Humanize a snake_case field name into a label ("repair_verdict" → "Repair verdict"). */
export function humanizeKey(key: string): string {
  return key
    .replace(/[._]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/\bId\b/, "ID")
    .replace(/\bUetr\b/i, "UETR")
    .replace(/\bBic\b/i, "BIC")
    .replace(/\bRfi\b/i, "RFI");
}

/** Is this a 0–1 confidence-style number we should render as a meter? */
export function isConfidenceField(key: string, schema: JsonSchema | undefined): boolean {
  const t = schemaType(schema);
  return (
    /confidence|score|probability/i.test(key) &&
    (t === "number" || t === "integer") &&
    (schema?.maximum === undefined || schema.maximum <= 1)
  );
}
