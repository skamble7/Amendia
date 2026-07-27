// ArtifactEditor.tsx — renders a HITL gate's artifacts (Part B). One tab per artifact (humanized name), so a
// multi-artifact gate — e.g. Task_ObtainInfo's `rfi` + `info_resolution`, or an input-context + output — shows
// every artifact, not just artifacts[0]. Editable artifacts render as schema-driven structured forms
// (ArtifactFields); read-only ones as ArtifactView. The assembled value is keyed by artifact NAME
// ({rfi:{…}, info_resolution:{…}}) — the shape the backend's `edits.get(spec.name)` expects — and each is
// validated against its own schema. A single submit (form={id}) spans all editable artifacts.
import { useEffect, useMemo, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { useForm, FormProvider } from "react-hook-form";
import { Braces, ListTree } from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { getArtifactSchema } from "@/api/services/registry";
import { parsePinnedRef, humanizeKey, type JsonSchema } from "@/components/artifact/schema";
import { ObjectFieldset, toDefault, parseValues, FieldParseError } from "@/components/artifact/ArtifactFields";
import { zodFromSchema } from "@/components/artifact/zodFromSchema";
import { ArtifactView } from "@/components/artifact/ArtifactView";
import type { PayloadArtifact } from "@/api/types";

/** Fetch every artifact's pinned schema (react-query dedupes with useArtifactSchema's cache). */
function useArtifactSchemas(refs: string[]): (JsonSchema | undefined)[] {
  const results = useQueries({
    queries: refs.map((ref) => {
      const parsed = parsePinnedRef(ref);
      return {
        queryKey: ["artifact-schema", ref],
        enabled: !!parsed,
        staleTime: Infinity,
        queryFn: async () =>
          ((await getArtifactSchema(parsed!.key, parsed!.version)).json_schema ?? {}) as JsonSchema,
      };
    }),
  });
  return results.map((r) => r.data as JsonSchema | undefined);
}

function objectDefaults(schema: JsonSchema | undefined, data: Record<string, unknown>): Record<string, unknown> {
  const keys = schema?.properties ? Object.keys(schema.properties) : Object.keys(data);
  const out: Record<string, unknown> = {};
  for (const k of keys) out[k] = toDefault(schema?.properties?.[k], data[k], k, 0);
  return out;
}

export interface ArtifactEditorProps {
  /** form element id — the parent renders the submit button with form={id} */
  id: string;
  artifacts: PayloadArtifact[];
  /** which artifacts the human authors/edits; the rest are read-only context. Default: all editable. */
  isEditable?: (a: PayloadArtifact) => boolean;
  /** called with edits keyed by artifact NAME once client validation passes. Omit for a read-only gate. */
  onSubmit?: (edits: Record<string, unknown> | undefined) => void;
  agentDrafted?: boolean;
  className?: string;
}

export function ArtifactEditor({ id, artifacts, isEditable, onSubmit, agentDrafted, className }: ArtifactEditorProps) {
  const schemas = useArtifactSchemas(artifacts.map((a) => a.schema));
  const schemaByName = useMemo(() => {
    const m: Record<string, JsonSchema | undefined> = {};
    artifacts.forEach((a, i) => (m[a.name] = schemas[i]));
    return m;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artifacts, ...schemas]);

  const canEdit = (a: PayloadArtifact) => !!onSubmit && (isEditable ? isEditable(a) : true);
  const editable = artifacts.filter(canEdit);

  const defaults = useMemo(() => {
    const d: Record<string, unknown> = {};
    for (const a of editable) d[a.name] = objectDefaults(schemaByName[a.name], a.data as Record<string, unknown>);
    return d;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artifacts, schemaByName]);

  const methods = useForm({ defaultValues: defaults });
  const { handleSubmit, reset, setError, getValues, setValue, formState: { isDirty } } = methods;

  // Per-artifact "Raw JSON" escape hatch: name → raw text (absent = structured form). The whole-artifact
  // fallback when the structured form can't express something; validated against the schema on submit.
  const [raw, setRaw] = useState<Record<string, string>>({});
  const [rawErr, setRawErr] = useState<Record<string, string>>({});

  const assembleStructured = (a: PayloadArtifact): Record<string, unknown> =>
    (parseValues(schemaByName[a.name], getValues(a.name), a.name, a.name, 0) as Record<string, unknown>) ?? {};

  function toggleRaw(a: PayloadArtifact) {
    setRawErr((e) => ({ ...e, [a.name]: "" }));
    setRaw((prev) => {
      if (prev[a.name] !== undefined) {
        // raw → structured: parse the blob back into the form; keep raw if it doesn't parse.
        try {
          const parsed = prev[a.name]!.trim() === "" ? {} : JSON.parse(prev[a.name]!);
          setValue(a.name as never, objectDefaults(schemaByName[a.name], parsed as Record<string, unknown>) as never);
        } catch {
          setRawErr((e) => ({ ...e, [a.name]: "Fix the JSON before switching back to the form" }));
          return prev;
        }
        const { [a.name]: _drop, ...rest } = prev;
        return rest;
      }
      // structured → raw: seed the blob from the current (assembled) values, best-effort.
      let seed: Record<string, unknown> = a.data as Record<string, unknown>;
      try {
        seed = assembleStructured(a);
      } catch {
        /* keep the original data */
      }
      return { ...prev, [a.name]: JSON.stringify(seed, null, 2) };
    });
  }

  // Re-apply defaults when they recompute (schemas resolve async / task changes) so fields hydrate without a
  // remount — only while pristine (Part A discipline, applied per-artifact under its name).
  useEffect(() => {
    if (!isDirty) reset(defaults);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaults, reset]);

  function submit(values: Record<string, unknown>) {
    const edits: Record<string, unknown> = {};
    try {
      for (const a of editable) {
        const schema = schemaByName[a.name];
        let assembled: Record<string, unknown>;
        if (raw[a.name] !== undefined) {
          try {
            assembled = raw[a.name]!.trim() === "" ? {} : (JSON.parse(raw[a.name]!) as Record<string, unknown>);
          } catch {
            setRawErr((e) => ({ ...e, [a.name]: "Invalid JSON" }));
            return;
          }
        } else {
          assembled = (parseValues(schema, values[a.name], a.name, a.name, 0) as Record<string, unknown>) ?? {};
        }
        const zres = zodFromSchema(schema).safeParse(assembled);
        if (!zres.success) {
          for (const issue of zres.error.issues) {
            setError([a.name, ...issue.path].join(".") as never, { message: issue.message });
          }
          return;
        }
        edits[a.name] = assembled;
      }
    } catch (e) {
      if (e instanceof FieldParseError) {
        setError(e.path as never, { message: e.message });
        return;
      }
      throw e;
    }
    // A gate with no editable outputs (e.g. a plain manual approval) must send NO edits — an empty object trips
    // the backend's "this task produces no editable output" guard.
    onSubmit?.(Object.keys(edits).length ? edits : undefined);
  }

  const renderBody = (a: PayloadArtifact) => {
    if (!canEdit(a)) return <ArtifactView name={a.name} data={a.data} schemaRef={a.schema} />;
    const isRaw = raw[a.name] !== undefined;
    return (
      <div className="space-y-2">
        <div className="flex justify-end">
          <Button type="button" variant="ghost" size="sm" className="h-7 gap-1 px-2 text-xs text-muted-foreground" onClick={() => toggleRaw(a)}>
            {isRaw ? <ListTree className="size-3.5" /> : <Braces className="size-3.5" />}
            {isRaw ? "Form" : "Raw JSON"}
          </Button>
        </div>
        {isRaw ? (
          <div className="space-y-1.5">
            <Textarea rows={12} className="font-mono text-xs" value={raw[a.name]} onChange={(e) => setRaw((p) => ({ ...p, [a.name]: e.target.value }))} aria-label={`${a.name} raw JSON`} />
            {rawErr[a.name] && <p className="text-xs text-danger">{rawErr[a.name]}</p>}
          </div>
        ) : (
          <ObjectFieldset name={a.name} schema={schemaByName[a.name]} data={a.data as Record<string, unknown>} idBase={`${id}-${a.name}`} depth={0} />
        )}
      </div>
    );
  };

  const content =
    artifacts.length === 0 ? null : artifacts.length === 1 ? (
      renderBody(artifacts[0]!)
    ) : (
      <Tabs defaultValue={artifacts[0]!.name}>
        <TabsList className="flex-wrap">
          {artifacts.map((a) => (
            <TabsTrigger key={a.name} value={a.name}>
              {humanizeKey(a.name)}
            </TabsTrigger>
          ))}
        </TabsList>
        {/* Inactive tabs unmount, but react-hook-form (shouldUnregister:false) retains each artifact's values
            and the per-artifact raw text lives in local state — so a single submit spans every artifact,
            visited or not. */}
        {artifacts.map((a) => (
          <TabsContent key={a.name} value={a.name} className="mt-3">
            {renderBody(a)}
          </TabsContent>
        ))}
      </Tabs>
    );

  // Read-only gate: no form wrapper, just the (tabbed) views.
  if (!onSubmit) return <div className={cn("space-y-3", className)}>{content}</div>;

  return (
    <FormProvider {...methods}>
      <form id={id} onSubmit={handleSubmit(submit)} className={cn("space-y-4", className)}>
        {agentDrafted && (
          <Badge variant="agent" className="gap-1.5">
            <span className="size-1.5 rounded-full bg-agent" /> Drafted by agent
          </Badge>
        )}
        {content}
      </form>
    </FormProvider>
  );
}
