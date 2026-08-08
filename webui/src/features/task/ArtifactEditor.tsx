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

/** Fetch every artifact's pinned schema (react-query dedupes with useArtifactSchema's cache).
 *  ADR-060: reads are pack-scoped, so each fetch needs the owning pack's coords (from the HITL task). */
function useArtifactSchemas(refs: string[], packKey?: string, packVersion?: string): SchemaEntry[] {
  const results = useQueries({
    queries: refs.map((ref) => {
      const parsed = parsePinnedRef(ref);
      return {
        queryKey: ["artifact-schema", packKey, packVersion, ref],
        enabled: !!parsed && !!packKey && !!packVersion,
        staleTime: Infinity,
        queryFn: async () =>
          ((await getArtifactSchema(packKey!, packVersion!, parsed!.key, parsed!.version)).json_schema ?? {}) as JsonSchema,
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
  /** ADR-060: owning pack coords (from the HITL task) — required to resolve each artifact's pack-scoped schema. */
  packKey?: string;
  packVersion?: string;
  /** which artifacts the human authors/edits; the rest are read-only context. Default: all editable. */
  isEditable?: (a: PayloadArtifact) => boolean;
  /** called with edits keyed by artifact NAME once client validation passes. Omit for a read-only gate. */
  onSubmit?: (edits: Record<string, unknown> | undefined) => void;
  agentDrafted?: boolean;
  className?: string;
}

/** One tab per artifact (or the single artifact bare). `renderBody` differs for read-only vs editable. When a
 *  submit is BLOCKED by client validation the parent controls the active tab (value/onValueChange) so the
 *  offending artifact is focused, and marks its tab via `errorNames` — so a blocked Complete is never silent. */
function TabbedArtifacts({ artifacts, renderBody, value, onValueChange, errorNames }: {
  artifacts: PayloadArtifact[];
  renderBody: (a: PayloadArtifact) => React.ReactNode;
  value?: string;
  onValueChange?: (v: string) => void;
  errorNames?: Set<string>;
}) {
  if (artifacts.length === 0) return null;
  if (artifacts.length === 1) return <>{renderBody(artifacts[0]!)}</>;
  const tabsProps = value !== undefined ? { value, onValueChange } : { defaultValue: artifacts[0]!.name };
  return (
    <Tabs {...tabsProps}>
      <TabsList className="flex-wrap">
        {artifacts.map((a) => {
          const errored = errorNames?.has(a.name) ?? false;
          return (
            <TabsTrigger key={a.name} value={a.name} aria-invalid={errored || undefined}
              className={cn(errored && "text-danger")}>
              {humanizeKey(a.name)}
              {errored && <span aria-hidden className="ml-1 inline-block size-1.5 rounded-full bg-danger" />}
            </TabsTrigger>
          );
        })}
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
function ReadOnlyArtifacts({ artifacts, packKey, packVersion, className }: ArtifactEditorProps) {
  return (
    <div className={cn("space-y-3", className)}>
      <TabbedArtifacts artifacts={artifacts} renderBody={(a) => <ArtifactView name={a.name} data={a.data} schemaRef={a.schema} packKey={packKey} packVersion={packVersion} />} />
    </div>
  );
}

/** Waits for the editable artifacts' schemas to settle, THEN mounts the form once with complete defaults. */
function EditableGate(props: ArtifactEditorProps) {
  const { id, artifacts, isEditable, packKey, packVersion, className } = props;
  const entries = useArtifactSchemas(artifacts.map((a) => a.schema), packKey, packVersion);
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
  id, artifacts, onSubmit, agentDrafted, className, packKey, packVersion, schemaByName, canEdit, editable,
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
  // Part A: a blocked Complete must never be a silent dead click. When client validation fails we record the
  // reason per artifact, focus that artifact's tab, and mark the tab — the human always sees WHY.
  const [blockErr, setBlockErr] = useState<Record<string, string>>({});
  const [active, setActive] = useState<string>(artifacts[0]?.name ?? "");

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

  /** The visible reason a required output blocks Complete: name the empty output, else the first field problem. */
  const blockReason = (a: PayloadArtifact, issues: { path: (string | number)[]; message: string }[],
                       assembled: Record<string, unknown>): string => {
    const label = humanizeKey(a.name);
    if (Object.keys(assembled).length === 0) return `${label} is required — fill it before completing.`;
    const first = issues[0];
    const field = first?.path?.length ? humanizeKey(String(first.path[first.path.length - 1])) : label;
    return `${label} — ${field}: ${first?.message ?? "invalid"}. Fix it before completing.`;
  };

  /** Surface a block on `a`: record the reason, focus its tab, mark it. Never a no-op. */
  const block = (name: string, message: string) => {
    setBlockErr({ [name]: message });
    setActive(name);
  };

  function submit(values: Record<string, unknown>) {
    const edits: Record<string, unknown> = {};
    setBlockErr({});
    try {
      for (const a of editable) {
        const schema = schemaByName[a.name];
        let assembled: Record<string, unknown>;
        if (raw[a.name] !== undefined) {
          try {
            assembled = raw[a.name]!.trim() === "" ? {} : (JSON.parse(raw[a.name]!) as Record<string, unknown>);
          } catch {
            setRawErr((e) => ({ ...e, [a.name]: "Invalid JSON" }));
            block(a.name, `${humanizeKey(a.name)} has invalid JSON — fix it before completing.`);
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
          block(a.name, blockReason(a, zres.error.issues, assembled));
          return;
        }
        edits[a.name] = assembled;
      }
    } catch (e) {
      if (e instanceof FieldParseError) {
        setError(e.path as never, { message: e.message });
        const name = String(e.path.split(".")[0] ?? editable[0]?.name ?? "");
        block(name, `${humanizeKey(name)} — ${e.message}. Fix it before completing.`);
        return;
      }
      throw e;
    }
    // A gate with no editable outputs (e.g. a plain manual approval) must send NO edits — an empty object trips
    // the backend's "this task produces no editable output" guard.
    onSubmit?.(Object.keys(edits).length ? edits : undefined);
  }

  const renderBody = (a: PayloadArtifact) => {
    if (!canEdit(a)) return <ArtifactView name={a.name} data={a.data} schemaRef={a.schema} packKey={packKey} packVersion={packVersion} />;
    const isRaw = raw[a.name] !== undefined;
    return (
      <div className="space-y-2">
        {blockErr[a.name] && (
          <p role="alert" className="rounded-md bg-danger/10 px-3 py-2 text-xs text-danger">{blockErr[a.name]}</p>
        )}
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
        <TabbedArtifacts
          artifacts={artifacts}
          renderBody={renderBody}
          value={active}
          onValueChange={setActive}
          errorNames={new Set(Object.keys(blockErr).filter((k) => blockErr[k]))}
        />
      </form>
    </FormProvider>
  );
}
