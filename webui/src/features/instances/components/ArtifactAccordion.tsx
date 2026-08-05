import { useState } from "react";
import { ChevronRight, Info } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ArtifactView } from "@/components/artifact/ArtifactView";
import { cn } from "@/lib/utils";
import type { InstanceDetail } from "@/api/types";

interface Props {
  instance: InstanceDetail;
  /** agent-runtime InstanceState.artifacts (values; debug-API gated). Absent → name-only fallback. */
  artifacts?: Record<string, unknown>;
  schemaByArtifact: Map<string, string>;
  /** artifact name -> producer element id (from glea lineage); empty when glea is absent. */
  producerByArtifactName: Map<string, string>;
}

/**
 * Artifacts as a collapsible accordion, **collapsed by default** (the main declutter, ADR-058 Phase E).
 * Each row: name + schema_ref + producer element; expand → the existing schema-aware ArtifactView.
 * Falls back to names + the debug-API note when the runtime debug API is off.
 */
export function ArtifactAccordion({ instance, artifacts, schemaByArtifact, producerByArtifactName }: Props) {
  const [open, setOpen] = useState<Set<string>>(new Set()); // collapsed by default
  const names = artifacts ? Object.keys(artifacts) : [];

  const toggle = (name: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  const allOpen = names.length > 0 && names.every((n) => open.has(n));
  const toggleAll = () => setOpen(allOpen ? new Set() : new Set(names));

  if (!artifacts) {
    // Debug API off → names only (graceful, same as before).
    if (instance.artifact_names.length === 0) {
      return <p className="text-sm text-muted-foreground">No artifacts yet.</p>;
    }
    return (
      <div className="space-y-2">
        <div className="flex items-start gap-2 rounded-md border border-border bg-surface/60 p-3 text-xs text-muted-foreground">
          <Info className="mt-0.5 size-3.5 shrink-0" />
          Artifact data requires the runtime debug API (<code className="font-mono">AGENTRT_ENABLE_DEBUG_API</code>).
          Names are shown below.
        </div>
        <div className="flex flex-wrap gap-1.5">
          {instance.artifact_names.map((n) => (
            <Badge key={n} variant="artifact">{n}</Badge>
          ))}
        </div>
      </div>
    );
  }

  if (names.length === 0) {
    return <p className="text-sm text-muted-foreground">No artifacts yet.</p>;
  }

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <span className="text-xs text-muted-foreground">{names.length} artifacts · collapsed by default</span>
        <button
          type="button"
          onClick={toggleAll}
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          {allOpen ? "Collapse all" : "Expand all"}
        </button>
      </div>
      <div className="space-y-2">
        {names.map((name) => {
          const isOpen = open.has(name);
          const schemaRef = schemaByArtifact.get(name);
          const producer = producerByArtifactName.get(name);
          return (
            <div key={name} className="overflow-hidden rounded-lg border border-border bg-surface">
              <button
                type="button"
                onClick={() => toggle(name)}
                aria-expanded={isOpen}
                className="flex w-full items-center gap-3 px-3.5 py-3 text-left hover:bg-surface/60"
              >
                <ChevronRight
                  className={cn("size-4 shrink-0 text-muted-foreground transition-transform", isOpen && "rotate-90")}
                />
                <span className="text-sm font-medium">{name}</span>
                {schemaRef ? <span className="font-mono text-[11px] text-muted-foreground">{schemaRef}</span> : null}
                {producer ? (
                  <span className="ml-auto font-mono text-[11px] text-muted-foreground">{producer}</span>
                ) : null}
              </button>
              {isOpen ? (
                <div className="border-t border-border p-3.5">
                  <ArtifactView
                    name={name}
                    data={artifacts[name] as Record<string, unknown>}
                    schemaRef={schemaRef}
                  />
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
