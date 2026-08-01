// lib/predicate.ts — the triage/gateway predicate vocabulary, shared by the technical wizard (Triage step) and
// the business copilot (Start triage builder). Mirrors the backend's closed op enum + per-type compatibility
// (app/validation/predicates.py). Single source of truth so both surfaces stay in lockstep with the backend.

/** The CLOSED predicate operator set (backend `_LEAF_OPS`). */
export const PREDICATE_OPS = ["eq", "ne", "in", "starts_with", "intersects", "exists", "gt", "gte", "lt", "lte"] as const;
export type PredicateOp = (typeof PREDICATE_OPS)[number];

/** Ops valid per JSON type (backend `_OPS_BY_TYPE`) — a field picker offers only its type-compatible operators. */
export const OPS_BY_TYPE: Record<string, string[]> = {
  array: ["intersects", "in", "exists"],
  string: ["eq", "ne", "in", "starts_with", "exists"],
  number: ["eq", "ne", "in", "gt", "gte", "lt", "lte", "exists"],
  integer: ["eq", "ne", "in", "gt", "gte", "lt", "lte", "exists"],
  boolean: ["eq", "ne", "exists"],
  object: ["exists"],
};

export const opsForType = (t?: string): string[] => (t && OPS_BY_TYPE[t]) || [...PREDICATE_OPS];  // unknown → all
export const defaultOpForType = (t?: string): string => (t === "array" ? "intersects" : "eq");

/** Coerce a raw string form value into the typed value the op/field expect (list for in/intersects, number, bool). */
export function coerceValue(op: string, raw: string, fieldType?: string): unknown {
  if (op === "in" || op === "intersects") return raw.split(",").map((x) => x.trim()).filter(Boolean);
  if (op === "exists") return raw === "true";
  if (["gt", "gte", "lt", "lte"].includes(op) && raw !== "" && !Number.isNaN(Number(raw))) return Number(raw);
  if ((fieldType === "number" || fieldType === "integer") && raw !== "" && !Number.isNaN(Number(raw))) return Number(raw);
  if (fieldType === "boolean") return raw === "true";
  return raw;
}

/** A single leaf predicate `{field, op, value}` (value omitted for `exists`). */
export function leafPredicate(field: string, op: string, raw: string, fieldType?: string): Record<string, unknown> {
  if (op === "exists") return { field, op };
  return { field, op, value: coerceValue(op, raw, fieldType) };
}
