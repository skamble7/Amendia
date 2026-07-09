import { useMemo } from "react";
import { useForm, Controller } from "react-hook-form";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { humanizeKey, schemaType, type JsonSchema } from "./schema";
import { zodFromSchema } from "./zodFromSchema";

interface FieldSpec {
  key: string;
  schema?: JsonSchema;
  kind: "enum" | "boolean" | "number" | "text" | "textarea" | "json";
  required: boolean;
}

function specFor(key: string, schema: JsonSchema | undefined, required: boolean): FieldSpec {
  const t = schemaType(schema);
  let kind: FieldSpec["kind"] = "text";
  if (schema?.enum) kind = "enum";
  else if (t === "boolean") kind = "boolean";
  else if (t === "number" || t === "integer") kind = "number";
  else if (t === "object" || t === "array") kind = "json";
  else if (/rationale|justification|message|narrative|comment|detail|notes/i.test(key)) kind = "textarea";
  return { key, schema, kind, required };
}

export interface ArtifactFormProps {
  /** form element id — parent renders submit buttons with form={id} */
  id: string;
  schema?: JsonSchema;
  /** the artifact data to edit / the agent-drafted prefill */
  defaultData: Record<string, unknown>;
  /** called with the assembled artifact object once client-side validation passes */
  onSubmit: (data: Record<string, unknown>) => void;
  /** show the purple "Drafted by agent" marker (manual tasks) */
  agentDrafted?: boolean;
  className?: string;
}

/**
 * Editable artifact form. Fields are derived from the pinned JSON Schema (falling
 * back to the data shape). Scalars/enums/numbers/booleans get native controls;
 * nested objects/arrays get a validated JSON editor. Client-side validation
 * mirrors the schema; the backend re-validates and its 400 detail is surfaced by
 * the caller on mismatch.
 */
export function ArtifactForm({ id, schema, defaultData, onSubmit, agentDrafted, className }: ArtifactFormProps) {
  const fields = useMemo<FieldSpec[]>(() => {
    const required = new Set(schema?.required ?? []);
    const keys = schema?.properties ? Object.keys(schema.properties) : Object.keys(defaultData);
    return keys.map((k) => specFor(k, schema?.properties?.[k], required.has(k)));
  }, [schema, defaultData]);

  const defaults = useMemo(() => {
    const d: Record<string, unknown> = {};
    for (const f of fields) {
      const v = defaultData[f.key];
      d[f.key] = f.kind === "json" ? JSON.stringify(v ?? (schemaType(f.schema) === "array" ? [] : {}), null, 2) : v ?? "";
    }
    return d;
  }, [fields, defaultData]);

  const {
    register,
    control,
    handleSubmit,
    formState: { errors },
    setError,
  } = useForm({ defaultValues: defaults });

  function submit(values: Record<string, unknown>) {
    const out: Record<string, unknown> = {};
    for (const f of fields) {
      const raw = values[f.key];
      if (f.kind === "json") {
        try {
          out[f.key] = raw === "" || raw == null ? undefined : JSON.parse(String(raw));
        } catch {
          setError(f.key, { message: "Invalid JSON" });
          return;
        }
      } else if (f.kind === "number") {
        out[f.key] = raw === "" || raw == null ? undefined : Number(raw);
      } else if (f.kind === "boolean") {
        out[f.key] = Boolean(raw);
      } else {
        out[f.key] = raw;
      }
    }
    // Validate the assembled artifact against the zod validator derived from the
    // pinned JSON Schema (required fields, enums, number bounds). The backend
    // re-validates authoritatively; this is fast local feedback.
    const parsed = zodFromSchema(schema).safeParse(out);
    if (!parsed.success) {
      for (const issue of parsed.error.issues) {
        const key = String(issue.path[0] ?? "");
        if (key) setError(key, { message: issue.message });
      }
      return;
    }
    onSubmit(out);
  }

  return (
    <form id={id} onSubmit={handleSubmit(submit)} className={cn("space-y-4", className)}>
      {agentDrafted && (
        <Badge variant="agent" className="gap-1.5">
          <span className="size-1.5 rounded-full bg-agent" /> Drafted by agent
        </Badge>
      )}
      {fields.map((f) => {
        const errMsg = errors[f.key]?.message as string | undefined;
        return (
          <div key={f.key} className="space-y-1.5">
            <Label htmlFor={`${id}-${f.key}`} className="flex items-center gap-1">
              {humanizeKey(f.key)}
              {f.required && <span className="text-danger">*</span>}
            </Label>

            {f.kind === "enum" && (
              <select
                id={`${id}-${f.key}`}
                {...register(f.key, { required: f.required })}
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {(f.schema?.enum ?? []).map((opt) => (
                  <option key={String(opt)} value={String(opt)}>
                    {String(opt)}
                  </option>
                ))}
              </select>
            )}

            {f.kind === "boolean" && (
              <Controller
                control={control}
                name={f.key}
                render={({ field }) => (
                  <Checkbox
                    id={`${id}-${f.key}`}
                    checked={Boolean(field.value)}
                    onCheckedChange={(v) => field.onChange(Boolean(v))}
                  />
                )}
              />
            )}

            {f.kind === "number" && (
              <Input id={`${id}-${f.key}`} type="number" step="any" {...register(f.key, { required: f.required })} />
            )}

            {f.kind === "text" && (
              <Input id={`${id}-${f.key}`} {...register(f.key, { required: f.required })} />
            )}

            {f.kind === "textarea" && (
              <Textarea id={`${id}-${f.key}`} rows={3} {...register(f.key, { required: f.required })} />
            )}

            {f.kind === "json" && (
              <Textarea
                id={`${id}-${f.key}`}
                rows={5}
                className="font-mono text-xs"
                {...register(f.key, { required: f.required })}
              />
            )}

            {errMsg && <p className="text-xs text-danger">{errMsg}</p>}
            {f.required && errors[f.key]?.type === "required" && !errMsg && (
              <p className="text-xs text-danger">Required</p>
            )}
          </div>
        );
      })}
    </form>
  );
}
