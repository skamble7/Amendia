import { useEffect, useMemo, useState } from "react";
import { useForm, FormProvider } from "react-hook-form";
import { Braces, ListTree } from "lucide-react";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { type JsonSchema } from "./schema";
import { zodFromSchema } from "./zodFromSchema";
import { ObjectFieldset, toDefault, parseValues, FieldParseError } from "./ArtifactFields";

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

/** Root-object defaults: structured nodes keep their raw shape (RHF nested fields / field arrays read them);
 *  freeform/schemaless leaves are JSON-stringified so a textarea shows readable JSON, never "[object Object]". */
function toFormDefaults(schema: JsonSchema | undefined, data: Record<string, unknown>): Record<string, unknown> {
  const keys = schema?.properties ? Object.keys(schema.properties) : Object.keys(data);
  const out: Record<string, unknown> = {};
  for (const k of keys) out[k] = toDefault(schema?.properties?.[k], data[k], k, 0);
  return out;
}

/**
 * Editable artifact form. Fields are derived recursively from the pinned JSON Schema (falling back to the
 * data shape while the schema loads): objects → nested fieldsets, arrays of objects → repeatable structured
 * rows, arrays of scalars → repeatable inputs, scalars → native controls. A schemaless/freeform subtree
 * degrades to a JSON textarea, and a per-form "Raw JSON" toggle is the whole-artifact escape hatch. The
 * assembled object is validated against the schema-derived zod validator (the backend re-validates).
 */
export function ArtifactForm({ id, schema, defaultData, onSubmit, agentDrafted, className }: ArtifactFormProps) {
  const defaults = useMemo(() => toFormDefaults(schema, defaultData), [schema, defaultData]);
  const [rawMode, setRawMode] = useState(false);
  const [rawText, setRawText] = useState("");
  const [rawError, setRawError] = useState<string | undefined>();

  const methods = useForm({ defaultValues: defaults });
  const { handleSubmit, reset, getValues, setError, formState: { isDirty } } = methods;

  // react-hook-form applies defaultValues only at mount; re-apply when they recompute (the schema resolves
  // async, or the task changes) so complex fields hydrate without a remount — only while pristine, so an
  // in-flight edit is never clobbered.
  useEffect(() => {
    if (!isDirty) reset(defaults);
    // isDirty is read at run-time as a guard, not a trigger — re-hydration keys off `defaults` changing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaults, reset]);

  /** Assemble the structured artifact from RHF values, coercing/parsing per schema, then zod-validate. */
  function submitStructured(values: Record<string, unknown>) {
    const keys = schema?.properties ? Object.keys(schema.properties) : Object.keys(values);
    const out: Record<string, unknown> = {};
    try {
      for (const k of keys) {
        const v = parseValues(schema?.properties?.[k], values[k], k, k, 0);
        if (v !== undefined) out[k] = v;
      }
    } catch (e) {
      if (e instanceof FieldParseError) {
        setError(e.path as never, { message: e.message });
        return;
      }
      throw e;
    }
    if (!validateAndReport(out)) return;
    onSubmit(out);
  }

  function submitRaw() {
    let parsed: unknown;
    try {
      parsed = rawText.trim() === "" ? {} : JSON.parse(rawText);
    } catch {
      setRawError("Invalid JSON");
      return;
    }
    if (!parsed || typeof parsed !== "object") {
      setRawError("Expected a JSON object");
      return;
    }
    if (!validateAndReport(parsed as Record<string, unknown>, setRawError)) return;
    onSubmit(parsed as Record<string, unknown>);
  }

  /** Validate against the schema-derived zod; report issues on the field (structured) or inline (raw). */
  function validateAndReport(out: Record<string, unknown>, onError?: (m: string) => void): boolean {
    const parsed = zodFromSchema(schema).safeParse(out);
    if (parsed.success) return true;
    if (onError) {
      const first = parsed.error.issues[0];
      onError(first ? `${first.path.join(".") || "root"}: ${first.message}` : "Invalid value");
    } else {
      for (const issue of parsed.error.issues) {
        const path = issue.path.join(".");
        if (path) setError(path as never, { message: issue.message });
      }
    }
    return false;
  }

  function onFormSubmit(e: React.FormEvent) {
    if (rawMode) {
      e.preventDefault();
      submitRaw();
      return;
    }
    handleSubmit(submitStructured)(e);
  }

  function toggleRaw() {
    if (!rawMode) {
      // structured → raw: seed the blob from the current (assembled) values, best-effort.
      let seed: Record<string, unknown> = defaultData;
      try {
        const values = getValues();
        const keys = schema?.properties ? Object.keys(schema.properties) : Object.keys(values);
        const out: Record<string, unknown> = {};
        for (const k of keys) {
          const v = parseValues(schema?.properties?.[k], values[k], k, k, 0);
          if (v !== undefined) out[k] = v;
        }
        seed = out;
      } catch {
        /* fall back to the original data on any parse issue */
      }
      setRawText(JSON.stringify(seed, null, 2));
      setRawError(undefined);
      setRawMode(true);
    } else {
      // raw → structured: parse the blob back into the form; keep raw mode if it doesn't parse.
      try {
        const parsed = rawText.trim() === "" ? {} : JSON.parse(rawText);
        reset(toFormDefaults(schema, parsed as Record<string, unknown>));
        setRawError(undefined);
        setRawMode(false);
      } catch {
        setRawError("Fix the JSON before switching back to the form");
      }
    }
  }

  return (
    <FormProvider {...methods}>
      <form id={id} onSubmit={onFormSubmit} className={cn("space-y-4", className)}>
        <div className="flex items-center justify-between">
          {agentDrafted ? (
            <Badge variant="agent" className="gap-1.5">
              <span className="size-1.5 rounded-full bg-agent" /> Drafted by agent
            </Badge>
          ) : (
            <span />
          )}
          <Button type="button" variant="ghost" size="sm" className="h-7 gap-1 px-2 text-xs text-muted-foreground" onClick={toggleRaw}>
            {rawMode ? <ListTree className="size-3.5" /> : <Braces className="size-3.5" />}
            {rawMode ? "Form" : "Raw JSON"}
          </Button>
        </div>

        {rawMode ? (
          <div className="space-y-1.5">
            <Textarea
              rows={14}
              className="font-mono text-xs"
              value={rawText}
              onChange={(e) => setRawText(e.target.value)}
              aria-label="Raw JSON"
            />
            {rawError && <p className="text-xs text-danger">{rawError}</p>}
          </div>
        ) : (
          <ObjectFieldset schema={schema} data={defaultData} idBase={id} depth={0} />
        )}
      </form>
    </FormProvider>
  );
}
