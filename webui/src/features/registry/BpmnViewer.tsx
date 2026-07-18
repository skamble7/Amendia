import { useEffect, useRef, useState } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * Per-element overlay state painted onto the diagram (see index.css `.bpmn-state-*`).
 * `done|current|pending|failed` are live-execution states (ProcessDiagramView); `executable|
 * documented|unknown` are the ADR-027 coverage tiers (onboarding wizard).
 */
export interface BpmnMarker {
  elementId: string;
  state: "done" | "current" | "pending" | "failed" | "executable" | "documented" | "unknown";
}

interface BpmnCanvas {
  zoom: (mode: string) => void;
  addMarker: (elementId: string, cls: string) => void;
}

/**
 * Renders a BPMN diagram from raw XML using bpmn-js (lazy-loaded to keep it out
 * of the main bundle). The seed BPMN ships DI layout, so it renders as-is.
 *
 * When `markers` are supplied, each element is painted with its execution state
 * (done / current / failed) so the diagram doubles as a live process tracker.
 */
export function BpmnViewer({
  xml,
  markers,
  className,
}: {
  xml: string | undefined;
  markers?: BpmnMarker[];
  className?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Re-run when the marker set changes (not just its identity) so the overlay
  // tracks the live process position without re-importing on every render.
  const markerKey = (markers ?? []).map((m) => `${m.elementId}:${m.state}`).join(",");

  useEffect(() => {
    if (!xml || !containerRef.current) return;
    let viewer: { importXML: (x: string) => Promise<unknown>; get: (n: string) => BpmnCanvas; destroy: () => void } | null = null;
    let cancelled = false;

    (async () => {
      try {
        const { default: NavigatedViewer } = await import("bpmn-js/dist/bpmn-navigated-viewer.production.min.js");
        if (cancelled || !containerRef.current) return;
        viewer = new NavigatedViewer({ container: containerRef.current });
        await viewer!.importXML(xml);
        const canvas = viewer!.get("canvas");
        canvas.zoom("fit-viewport");
        for (const m of markers ?? []) {
          if (m.state === "pending") continue; // pending = default diagram look
          try {
            canvas.addMarker(m.elementId, `bpmn-state-${m.state}`);
          } catch {
            /* element id not present in this diagram — skip */
          }
        }
        setLoading(false);
      } catch (e) {
        if (!cancelled) {
          setError((e as Error).message);
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
      viewer?.destroy();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [xml, markerKey]);

  if (error) return <p className="text-sm text-danger">Could not render diagram: {error}</p>;

  return (
    <div className="relative">
      {loading && <Skeleton className="absolute inset-0 h-full w-full" />}
      <div ref={containerRef} className={cn("w-full overflow-hidden rounded-md border border-border bg-canvas", className ?? "h-[420px]")} />
    </div>
  );
}
