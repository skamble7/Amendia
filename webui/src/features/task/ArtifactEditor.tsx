// ArtifactEditor.tsx — renders a HITL gate's artifacts (Part B). One tab per artifact (humanized name), so a
// multi-artifact gate — e.g. Task_ObtainInfo's `rfi` + `info_resolution`, or an input-context + output — shows
// every artifact, not just artifacts[0]. Editable artifacts render as schema-driven structured forms
// (ArtifactFields); read-only ones as ArtifactView. The assembled value is keyed by artifact NAME
// ({rfi:{…}, info_resolution:{…}}) — the shape the backend's `edits.get(spec.name)` expects — and each is
// validated against its own schema. A single submit (form={id}) spans all editable artifacts.
//
// Hydration (regression-critical): the edit form is mounted ONLY once every editable artifact's schema has
// settled, so react-hook-form (and useFieldArray inside ArtifactFields) initialize from COMPLETE defaultValues
// in a single mount. A later reset() reliably backfills scalars but NOT a field array — which is what made an
// agent-drafted "Edit & approve" open with empty Corrections. Gate-then-mount sidesteps that timing class.
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

interface SchemaEntry {
  schema: JsonSchema | undefined;
  /** the query has resolved (success/error) or is disabled — i.e. we will get no more updates for it. */
  settled: boolean;
}

/** Fetch every artifact's pinned schema (react-query dedupes with useArtifactSchema's cache). */
function useArtifactSchemas(refs: string[]): SchemaEntry[] {
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
  return results.map((r) => ({
    schema: r.data as JsonSchema | undefined,
    settled: r.isSuccess || r.isError || r.fetchStatus === "idle",
  }));
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

/** One tab per artifact (or the single artifact bare). `renderBody` differs for read-only vs editable. */
function TabbedArtifacts({ artifacts, renderBody }: {
  artifacts: PayloadArtifact[];
  renderBody: (a: PayloadArtifact) => React.ReactNode;
}) {
  if (artifacts.length === 0) return null;
  if (artifacts.length === 1) return <>{renderBody(artifacts[0]!)}</>;
  return (
    <Tabs defaultValue={artifacts[0]!.name}>
      <TabsList className="flex-wrap">
        {artifacts.map((a) => (
          <TabsTrigger key={a.name} value={a.name}>{humanizeKey(a.name)}</TabsTrigger>
        ))}
      </TabsList>
      {/* Inactive tabs unmount, but react-hook-form (shouldUnregister:false) retains each artifact's values and
          the per-artifact raw text lives in local state — so a single submit spans every artifact, visited or not. */}
      {artifacts.map((a) => (
        <TabsContent key={a.name} value={a.name} className="mt-3">{renderBody(a)}</TabsContent>
      ))}
    </Tabs>
  );
}

export function ArtifactEditor(props: ArtifactEditorProps) {
  return props.onSubmit ? <EditableGate {...props} /> : <ReadOnlyArtifacts {...props} />;
}

/** Read-only gate: tabbed ArtifactViews, no form. Each view fetches its own schema. */
function ReadOnlyArtifacts({ artifacts, className }: ArtifactEditorProps) {
  return (
    <div className={cn("space-y-3", className)}>
      <TabbedArtifacts artifacts={artifacts} renderBody={(a) => <ArtifactView name={a.name} data={a.data} schemaRef={a.schema} />} />
    </div>
  );
}

/** Waits for the editable artifacts' schemas to settle, THEN mounts the form once with complete defaults. */
function EditableGate(props: ArtifactEditorProps) {
  const { id, artifacts, isEditable, className } = props;
  const entries = useArtifactSchemas(artifacts.map((a) => a.schema));
  const schemaByName = useMemo(() => {
    const m: Record<string, JsonSchema | undefined> = {};
    artifacts.forEach((a, i) => (m[a.name] = entries[i]?.schema));
    return m;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artifacts, ...entries.map((e) => e.schema)]);

  const canEdit = (a: PayloadArtifact) => (isEditable ? isEditable(a) : true);
  const editable = artifacts.filter(canEdit);
  const ready = editable.every((a) => entries[artifacts.indexOf(a)]?.settled);

  if (!ready) return <p className={cn("text-sm text-muted-foreground", className)}>Loading form…</p>;
  // `key={id}` → the form mounts once per task (id carries task_id) with COMPLETE defaults; a task change
  // remounts it with the new draft, and useFieldArray therefore always reads populated rows at mount.
  return <EditForm key={id} {...props} schemaByName={schemaByName} canEdit={canEdit} editable={editable} />;
}

function EditForm({
  id, artifacts, onSubmit, agentDrafted, className, schemaByName, canEdit, editable,
}: ArtifactEditorProps & {
  schemaByName: Record<string, JsonSchema | undefined>;
  canEdit: (a: PayloadArtifact) => boolean;
  editable: PayloadArtifact[];
}) {
  // Computed at mount from already-settled schemas → COMPLETE. useForm reads it once; useFieldArray populates.
  const defaults = useMemo(() => {
    const d: Record<string, unknown> = {};
    for (const a of editable) d[a.name] = objectDefaults(schemaByName[a.name], a.data as Record<string, unknown>);
    return d;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artifacts, schemaByName]);

  const methods = useForm({ defaultValues: defaults });
  const { handleSubmit, reset, setError, getValues, setValue, formState: { isDirty } } = methods;

  // Defensive re-hydration if the draft data changes while the form is still pristine (never clobbers edits).
  useEffect(() => {
    if (!isDirty) reset(defaults);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaults, reset]);

  const [raw, setRaw] = useState<Record<string, string>>({});
  const [rawErr, setRawErr] = useState<Record<string, string>>({});

  const assembleStructured = (a: PayloadArtifact): Record<string, unknown> =>
    (parseValues(schemaByName[a.name], getValues(a.name), a.name, a.name, 0) as Record<string, unknown>) ?? {};

  function toggleRaw(a: PayloadArtifact) {
    setRawErr((e) => ({ ...e, [a.name]: "" }));
    setRaw((prev) => {
      if (prev[a.name] !== undefined) {
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
      let seed: Record<string, unknown> = a.data as Record<string, unknown>;
      try {
        seed = assembleStructured(a);
      } catch {
        /* keep the original data */
      }
      return { ...prev, [a.name]: JSON.stringify(seed, null, 2) };
    });
  }

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

  return (
    <FormProvider {...methods}>
      <form id={id} onSubmit={handleSubmit(submit)} className={cn("space-y-4", className)}>
        {agentDrafted && (
          <Badge variant="agent" className="gap-1.5">
            <span className="size-1.5 rounded-full bg-agent" /> Drafted by agent
          </Badge>
        )}
        <TabbedArtifacts artifacts={artifacts} renderBody={renderBody} />
      </form>
    </FormProvider>
  );
}
