// SchemaRefiner — ADR-054 Part B. Turns a loose derived human-artifact schema into a clean, labeled, form-friendly
// one: per-property type / label (JSON Schema `title`) / required / enum options, with add & remove. Emits a
// concrete draft-2020-12 object schema on every edit so a live ArtifactForm preview can render exactly the HITL form.
import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { type JsonSchema } from "@/components/artifact/schema";

export const PROP_TYPES = ["string", "number", "boolean", "enum", "object", "array"] as const;
export type PropType = (typeof PROP_TYPES)[number];

interface PropRow {
  name: string;
  type: PropType;
  title: string;
  required: boolean;
  enumOptions: string; // comma-separated in the input; parsed into `enum` on build
}

const selectCls =
  "flex h-8 rounded-md border border-input bg-transparent px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function rowType(s: JsonSchema | undefined): PropType {
  if (s?.enum) return "enum";
  const t = Array.isArray(s?.type) ? s?.type?.[0] : s?.type;
  if (t === "integer" || t === "number") return "number";
  if (t === "boolean") return "boolean";
  if (t === "object") return "object";
  if (t === "array") return "array";
  return "string";
}

export function schemaToRows(schema: JsonSchema): PropRow[] {
  const props = schema.properties ?? {};
  const req = new Set(schema.required ?? []);
  return Object.entries(props).map(([name, s]) => ({
    name,
    type: rowType(s),
    title: typeof s.title === "string" ? s.title : "",
    required: req.has(name),
    enumOptions: Array.isArray(s.enum) ? s.enum.map(String).join(", ") : "",
  }));
}

function propSchema(r: PropRow): JsonSchema {
  const title = r.title.trim() ? { title: r.title.trim() } : {};
  switch (r.type) {
    case "enum":
      return { type: "string", enum: r.enumOptions.split(",").map((o) => o.trim()).filter(Boolean), ...title };
    case "number":
      return { type: "number", ...title };
    case "boolean":
      return { type: "boolean", ...title };
    case "object":
      return { type: "object", properties: {}, ...title };
    case "array":
      return { type: "array", items: { type: "string" }, ...title };
    default:
      return { type: "string", ...title };
  }
}

/** Rows → a concrete, closed draft-2020-12 object schema (the shape the runtime HITL form renders from). */
export function rowsToSchema(rows: PropRow[]): JsonSchema {
  const properties: Record<string, JsonSchema> = {};
  for (const r of rows) if (r.name.trim()) properties[r.name.trim()] = propSchema(r);
  return {
    type: "object",
    properties,
    required: rows.filter((r) => r.required && r.name.trim()).map((r) => r.name.trim()),
    additionalProperties: false,
    $schema: "https://json-schema.org/draft/2020-12/schema",
  };
}

export function SchemaRefiner({ schema, onChange }: { schema: JsonSchema; onChange: (s: JsonSchema) => void }) {
  const [rows, setRows] = useState<PropRow[]>(() => schemaToRows(schema));

  const update = (next: PropRow[]) => {
    setRows(next);
    onChange(rowsToSchema(next));
  };
  const setRow = (i: number, patch: Partial<PropRow>) => update(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const addRow = () => update([...rows, { name: "", type: "string", title: "", required: false, enumOptions: "" }]);
  const removeRow = (i: number) => update(rows.filter((_, j) => j !== i));

  return (
    <div className="space-y-2">
      {rows.map((r, i) => (
        <div key={i} className="space-y-2 rounded-md border border-border p-2">
          <div className="flex items-center gap-2">
            <Input aria-label={`property ${i} name`} placeholder="property name" value={r.name}
              onChange={(e) => setRow(i, { name: e.target.value })} className="h-8 flex-1" />
            <select aria-label={`property ${i} type`} className={selectCls} value={r.type}
              onChange={(e) => setRow(i, { type: e.target.value as PropType })}>
              {PROP_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <Button type="button" variant="ghost" size="sm" className="h-8 px-2"
              aria-label={`remove property ${i}`} onClick={() => removeRow(i)}>
              <Trash2 className="size-3.5" />
            </Button>
          </div>
          <div className="flex items-center gap-2">
            <Input aria-label={`property ${i} label`} placeholder="label shown on the form" value={r.title}
              onChange={(e) => setRow(i, { title: e.target.value })} className="h-8 flex-1" />
            <label className="flex select-none items-center gap-1 whitespace-nowrap text-xs text-muted-foreground">
              <input type="checkbox" checked={r.required} aria-label={`property ${i} required`}
                onChange={(e) => setRow(i, { required: e.target.checked })} />
              required
            </label>
          </div>
          {r.type === "enum" && (
            <Input aria-label={`property ${i} options`} className="h-8"
              placeholder="options, comma-separated (e.g. dine_in, takeaway)" value={r.enumOptions}
              onChange={(e) => setRow(i, { enumOptions: e.target.value })} />
          )}
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" onClick={addRow} className="gap-1">
        <Plus className="size-3.5" /> Add property
      </Button>
    </div>
  );
}
