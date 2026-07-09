import { useState } from "react";
import { ChevronDown, Code2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { humanizeKey, isConfidenceField, schemaType, type JsonSchema } from "./schema";
import { useArtifactSchema } from "./useArtifactSchema";
import { CUSTOM_RENDERERS } from "./renderers";

/** enum → outcome color (verdict/result chips). */
export function enumTone(value: string): "success" | "danger" | "attention" | "default" {
  const v = value.toLowerCase();
  if (["clean", "repairable", "approved", "complete", "completed", "resolved", "pass", "success"].includes(v)) return "success";
  if (["hit", "unrepairable", "rejected", "failed", "blocked", "fail"].includes(v)) return "danger";
  if (["review", "needs_info", "pending", "manual", "warning"].includes(v)) return "attention";
  return "default";
}

function ConfidenceMeter({ value }: { value: number }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  const tone = pct >= 80 ? "bg-success" : pct >= 50 ? "bg-attention" : "bg-danger";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${pct}%` }} />
      </div>
      <span className="tabular-nums text-sm">{pct}%</span>
    </div>
  );
}

function ScalarValue({ keyName, value, schema }: { keyName: string; value: unknown; schema?: JsonSchema }) {
  if (value === null || value === undefined) return <span className="text-muted-foreground">—</span>;
  if (typeof value === "boolean") return <Badge variant={value ? "success" : "default"}>{value ? "Yes" : "No"}</Badge>;
  if (typeof value === "number" && isConfidenceField(keyName, schema)) return <ConfidenceMeter value={value} />;
  if (schema?.enum || (typeof value === "string" && /verdict|result|status|kind/i.test(keyName))) {
    return <Badge variant={enumTone(String(value))}>{String(value)}</Badge>;
  }
  const isId = /id$|uetr|iban|bic|account/i.test(keyName);
  return <span className={cn("break-words", isId && "font-mono tabular-nums text-sm")}>{String(value)}</span>;
}

function FieldRow({ keyName, value, schema }: { keyName: string; value: unknown; schema?: JsonSchema }) {
  const propSchema = schema?.properties?.[keyName];
  const t = schemaType(propSchema);

  if (Array.isArray(value)) {
    return (
      <div className="space-y-2">
        <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{humanizeKey(keyName)}</p>
        {value.length === 0 ? (
          <p className="text-sm text-muted-foreground">None</p>
        ) : (
          <div className="space-y-2">
            {value.map((item, i) => (
              <div key={i} className="rounded-md border border-border bg-surface/50 p-2.5">
                {item && typeof item === "object" ? (
                  <FieldGroup data={item as Record<string, unknown>} schema={propSchema?.items} compact />
                ) : (
                  <ScalarValue keyName={keyName} value={item} schema={propSchema?.items} />
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  if (value && typeof value === "object" && (t === "object" || t === "unknown")) {
    return (
      <div className="space-y-1.5">
        <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{humanizeKey(keyName)}</p>
        <div className="rounded-md border border-border bg-surface/50 p-2.5">
          <FieldGroup data={value as Record<string, unknown>} schema={propSchema} compact />
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-baseline justify-between gap-4 py-1">
      <span className="text-sm text-muted-foreground">{humanizeKey(keyName)}</span>
      <div className="text-right">
        <ScalarValue keyName={keyName} value={value} schema={propSchema} />
      </div>
    </div>
  );
}

function FieldGroup({
  data,
  schema,
  compact,
}: {
  data: Record<string, unknown>;
  schema?: JsonSchema;
  compact?: boolean;
}) {
  const keys = Object.keys(data);
  return (
    <div className={cn(compact ? "space-y-1" : "space-y-2.5")}>
      {keys.map((k) => (
        <FieldRow key={k} keyName={k} value={data[k]} schema={schema} />
      ))}
    </div>
  );
}

export interface ArtifactViewProps {
  /** artifact state name (e.g. "beneficiary") */
  name?: string;
  /** the artifact data snapshot */
  data: Record<string, unknown> | unknown;
  /** pinned schema ref (art.x@1.2.3) — fetched for labels/enums/required if given */
  schemaRef?: string;
  /** artifact_key for custom-renderer lookup (derived from schemaRef when omitted) */
  artifactKey?: string;
  className?: string;
}

/**
 * Read-only, schema-aware artifact renderer. Walks the pinned JSON Schema:
 * objects → labeled field groups, enums → outcome-colored chips, 0–1 confidence
 * → meter, arrays → cards, and the correction shapes → before→after diffs (via
 * the custom-renderer registry). Unknown shapes degrade to a tidy field tree;
 * raw JSON is available behind a toggle.
 */
export function ArtifactView({ name, data, schemaRef, artifactKey, className }: ArtifactViewProps) {
  const [rawOpen, setRawOpen] = useState(false);
  const { data: schema } = useArtifactSchema(schemaRef);

  const key = artifactKey ?? (schemaRef ? schemaRef.split("@")[0] : undefined);
  const Custom = key ? CUSTOM_RENDERERS[key] : undefined;

  const record = data && typeof data === "object" ? (data as Record<string, unknown>) : null;

  return (
    <div className={cn("space-y-3", className)}>
      {name && (
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium">{humanizeKey(name)}</p>
          {schemaRef && <Badge variant="artifact" className="font-mono text-[10px]">{schemaRef}</Badge>}
        </div>
      )}

      {Custom && record ? (
        <Custom data={record} schema={schema} />
      ) : record ? (
        <FieldGroup data={record} schema={schema} />
      ) : (
        <ScalarValue keyName={name ?? ""} value={data} schema={schema} />
      )}

      <div>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 gap-1 px-2 text-xs text-muted-foreground"
          onClick={() => setRawOpen((o) => !o)}
        >
          <Code2 className="size-3.5" />
          Raw JSON
          <ChevronDown className={cn("size-3.5 transition-transform", rawOpen && "rotate-180")} />
        </Button>
        {rawOpen && (
          <pre className="mt-1 max-h-72 overflow-auto rounded-md border border-border bg-surface p-3 text-xs">
            {JSON.stringify(data, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}

export { FieldGroup };
