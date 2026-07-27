// ArtifactFields.tsx — recursive, schema-driven form fields for ArtifactForm (Part B).
//
// Renders the pinned JSON Schema as structured controls instead of one raw-JSON textarea:
//   object              → nested fieldset, recursing over `properties`
//   array of objects    → repeatable structured rows (add/remove), built from `items`
//   array of scalars    → repeatable simple inputs (add/remove)
//   enum/bool/number/str → native controls (narrative keys → textarea)
//   schemaless/freeform  → a JSON textarea FALLBACK (the only place raw JSON survives inline)
//
// The assembled value is the structured artifact object — `parseValues` mirrors `toDefault` so numbers are
// coerced and freeform JSON leaves are parsed; the result is validated against `zodFromSchema` by the caller.
import { useFormContext, useFieldArray, Controller } from "react-hook-form";
import { Plus, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { humanizeKey, schemaType, type JsonSchema } from "./schema";

export type FieldKind =
  | "enum" | "boolean" | "number" | "text" | "textarea"
  | "object" | "arrayObjects" | "arrayScalars" | "json";

const NARRATIVE = /rationale|justification|message|narrative|comment|detail|notes|description|summary/i;
const MAX_DEPTH = 6; // artifact schemas are shallow; beyond this, degrade to a JSON textarea

/** Classify a field for editing — schema first, then the runtime VALUE shape when the schema is absent or
 *  indeterminate (the async-load window from Part A, or a genuinely freeform subtree). */
export function fieldKind(schema: JsonSchema | undefined, value: unknown, key: string): FieldKind {
  if (schema?.enum) return "enum";
  const t = schemaType(schema);
  if (t === "boolean") return "boolean";
  if (t === "number" || t === "integer") return "number";
  // Object/array kinds are decided from the SCHEMA, not the runtime value — so classification is stable
  // whether the value is still raw or already stringified (toDefault ⇄ parseValues must agree). A typed
  // object/array WITHOUT properties/items is genuinely freeform → the JSON-textarea fallback.
  if (t === "object") return schema?.properties && Object.keys(schema.properties).length ? "object" : "json";
  if (t === "array") {
    if (!schema?.items) return "json";
    const it = schema.items;
    return schemaType(it) === "object" && it.properties ? "arrayObjects" : "arrayScalars";
  }
  // Schema truly absent/indeterminate (the async-load window) → fall back to the value shape so a complex
  // value is never handed to a text input.
  if (Array.isArray(value) || (typeof value === "object" && value !== null)) return "json";
  return NARRATIVE.test(key) ? "textarea" : "text";
}

const emptyForType = (schema: JsonSchema | undefined) => (schemaType(schema) === "array" ? [] : {});

/** Build the react-hook-form default for a value: structured nodes keep their raw shape (RHF reads nested
 *  fields / field arrays from it), json leaves are stringified so a textarea shows readable JSON. */
export function toDefault(schema: JsonSchema | undefined, value: unknown, key: string, depth = 0): unknown {
  const kind = depth >= MAX_DEPTH ? "json" : fieldKind(schema, value, key);
  switch (kind) {
    case "json":
      return JSON.stringify(value ?? emptyForType(schema), null, 2);
    case "arrayObjects":
      return (Array.isArray(value) ? value : []).map((v) => toDefaultObject(schema!.items, v, depth + 1));
    case "arrayScalars":
      return (Array.isArray(value) ? value : []).map((v) => (v ?? ""));
    case "object":
      return toDefaultObject(schema, value, depth + 1);
    case "boolean":
      return Boolean(value);
    default: // number / text / textarea / enum
      return value ?? "";
  }
}

function toDefaultObject(schema: JsonSchema | undefined, value: unknown, depth: number): Record<string, unknown> {
  const obj = (value && typeof value === "object" ? value : {}) as Record<string, unknown>;
  const keys = schema?.properties ? Object.keys(schema.properties) : Object.keys(obj);
  const out: Record<string, unknown> = {};
  for (const k of keys) out[k] = toDefault(schema?.properties?.[k], obj[k], k, depth);
  return out;
}

/** A structural error carrying the field path — thrown by `parseValues` on invalid freeform JSON. */
export class FieldParseError extends Error {
  constructor(public path: string, message: string) {
    super(message);
  }
}

/** Reverse of `toDefault`: assemble the structured artifact from RHF values — coerce numbers, parse freeform
 *  JSON leaves, drop empty optional scalars. Throws {@link FieldParseError} (with the path) on bad JSON. */
export function parseValues(schema: JsonSchema | undefined, value: unknown, key: string, path = "", depth = 0): unknown {
  const kind = depth >= MAX_DEPTH ? "json" : fieldKind(schema, value, key);
  switch (kind) {
    case "json": {
      const s = value == null ? "" : String(value);
      if (s.trim() === "") return undefined;
      try {
        return JSON.parse(s);
      } catch {
        throw new FieldParseError(path, "Invalid JSON");
      }
    }
    case "arrayObjects":
      return (Array.isArray(value) ? value : []).map((v, i) =>
        parseObject(schema!.items, v, `${path}.${i}`, depth + 1));
    case "arrayScalars":
      return (Array.isArray(value) ? value : []).map((v) => v);
    case "object":
      return parseObject(schema, value, path, depth + 1);
    case "number":
      return value === "" || value == null ? undefined : Number(value);
    case "boolean":
      return Boolean(value);
    default: // text / textarea / enum
      return value === "" || value == null ? undefined : value;
  }
}

function parseObject(schema: JsonSchema | undefined, value: unknown, path: string, depth: number): Record<string, unknown> {
  const obj = (value && typeof value === "object" ? value : {}) as Record<string, unknown>;
  const keys = schema?.properties ? Object.keys(schema.properties) : Object.keys(obj);
  const out: Record<string, unknown> = {};
  for (const k of keys) {
    const v = parseValues(schema?.properties?.[k], obj[k], k, path ? `${path}.${k}` : k, depth);
    if (v !== undefined) out[k] = v;
  }
  return out;
}

// --------------------------------------------------------------------------- #
// Rendering
// --------------------------------------------------------------------------- #

function FieldLabel({ id, keyName, schema, required }: { id: string; keyName: string; schema?: JsonSchema; required?: boolean }) {
  return (
    <Label htmlFor={id} className="flex items-center gap-1">
      {schema?.title || humanizeKey(keyName)}
      {required && <span className="text-danger">*</span>}
    </Label>
  );
}

function ScalarControl({ name, id, kind, schema, required }: {
  name: string; id: string; kind: FieldKind; schema?: JsonSchema; required?: boolean;
}) {
  const { register, control } = useFormContext();
  if (kind === "enum") {
    return (
      <select id={id} {...register(name, { required })}
        className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {(schema?.enum ?? []).map((opt) => (
          <option key={String(opt)} value={String(opt)}>{String(opt)}</option>
        ))}
      </select>
    );
  }
  if (kind === "boolean") {
    return (
      <Controller control={control} name={name}
        render={({ field }) => (
          <Checkbox id={id} checked={Boolean(field.value)} onCheckedChange={(v) => field.onChange(Boolean(v))} />
        )} />
    );
  }
  if (kind === "number") return <Input id={id} type="number" step="any" {...register(name, { required })} />;
  if (kind === "textarea") return <Textarea id={id} rows={3} {...register(name, { required })} />;
  if (kind === "json") return <Textarea id={id} rows={5} className="font-mono text-xs" {...register(name, { required })} />;
  return <Input id={id} {...register(name, { required })} />;
}

/** array of objects / array of scalars → repeatable rows with add/remove (useFieldArray). */
function ArrayFieldset({ name, itemSchema, kind, idBase, depth }: {
  name: string; itemSchema?: JsonSchema; kind: FieldKind; idBase: string; depth: number;
}) {
  const { control } = useFormContext();
  const { fields, append, remove } = useFieldArray({ control, name });
  const addOne = () =>
    append(kind === "arrayObjects" ? toDefaultObject(itemSchema, {}, depth + 1) : "");
  return (
    <div className="space-y-2 rounded-md border border-border/70 bg-surface/40 p-2.5">
      {fields.length === 0 && <p className="text-xs text-muted-foreground">None yet.</p>}
      {fields.map((f, i) => (
        <div key={f.id} className="flex items-start gap-2">
          <div className="min-w-0 flex-1 space-y-2">
            {kind === "arrayObjects" ? (
              <ObjectFieldset name={`${name}.${i}`} schema={itemSchema} idBase={`${idBase}-${i}`} depth={depth + 1} compact />
            ) : (
              <ScalarControl name={`${name}.${i}`} id={`${idBase}-${i}`} kind={fieldKind(itemSchema, undefined, name)} schema={itemSchema} />
            )}
          </div>
          <Button type="button" variant="ghost" size="sm" className="mt-0.5 h-7 px-2 text-muted-foreground" onClick={() => remove(i)} aria-label="Remove item">
            <X className="size-3.5" />
          </Button>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" className="h-7 gap-1 px-2 text-xs" onClick={addOne}>
        <Plus className="size-3.5" /> Add
      </Button>
    </div>
  );
}

/** An object → a fieldset of its properties (each a <Field>). The recursion root. */
export function ObjectFieldset({ name, schema, data, idBase, depth = 0, compact }: {
  name?: string; schema?: JsonSchema; data?: Record<string, unknown>; idBase: string; depth?: number; compact?: boolean;
}) {
  const keys = schema?.properties ? Object.keys(schema.properties) : Object.keys(data ?? {});
  const required = new Set(schema?.required ?? []);
  return (
    <div className={cn(compact ? "space-y-2.5" : "space-y-4")}>
      {keys.map((k) => (
        <Field
          key={k}
          name={name ? `${name}.${k}` : k}
          keyName={k}
          schema={schema?.properties?.[k]}
          fallbackValue={data?.[k]}
          required={required.has(k)}
          idBase={idBase}
          depth={depth}
        />
      ))}
    </div>
  );
}

function Field({ name, keyName, schema, fallbackValue, required, idBase, depth }: {
  name: string; keyName: string; schema?: JsonSchema; fallbackValue?: unknown; required: boolean; idBase: string; depth: number;
}) {
  const { getValues } = useFormContext();
  // classify from schema first; when it is indeterminate use the current RHF value (or the seed data).
  const value = getValues(name) ?? fallbackValue;
  const kind = depth >= MAX_DEPTH ? "json" : fieldKind(schema, value, keyName);
  const id = `${idBase}-${name}`;

  if (kind === "object") {
    return (
      <fieldset className="space-y-2">
        <FieldLabel id={id} keyName={keyName} schema={schema} required={required} />
        <div className="rounded-md border border-border/70 bg-surface/40 p-2.5">
          <ObjectFieldset name={name} schema={schema} idBase={idBase} depth={depth + 1} compact />
        </div>
      </fieldset>
    );
  }
  if (kind === "arrayObjects" || kind === "arrayScalars") {
    return (
      <fieldset className="space-y-1.5">
        <FieldLabel id={id} keyName={keyName} schema={schema} required={required} />
        <ArrayFieldset name={name} itemSchema={schema?.items} kind={kind} idBase={id} depth={depth} />
      </fieldset>
    );
  }
  return (
    <div className="space-y-1.5">
      <FieldLabel id={id} keyName={keyName} schema={schema} required={required} />
      <ScalarControl name={name} id={id} kind={kind} schema={schema} required={required} />
    </div>
  );
}
