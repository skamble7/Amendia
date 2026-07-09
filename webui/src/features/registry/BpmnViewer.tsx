import { useEffect, useRef, useState } from "react";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Renders a BPMN diagram from raw XML using bpmn-js (lazy-loaded to keep it out
 * of the main bundle). The seed BPMN ships DI layout, so it renders as-is.
 */
export function BpmnViewer({ xml }: { xml: string | undefined }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!xml || !containerRef.current) return;
    let viewer: { importXML: (x: string) => Promise<unknown>; get: (n: string) => { zoom: (m: string) => void }; destroy: () => void } | null = null;
    let cancelled = false;

    (async () => {
      try {
        const { default: NavigatedViewer } = await import("bpmn-js/dist/bpmn-navigated-viewer.production.min.js");
        if (cancelled || !containerRef.current) return;
        viewer = new NavigatedViewer({ container: containerRef.current });
        await viewer!.importXML(xml);
        viewer!.get("canvas").zoom("fit-viewport");
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
  }, [xml]);

  if (error) return <p className="text-sm text-danger">Could not render diagram: {error}</p>;

  return (
    <div className="relative">
      {loading && <Skeleton className="absolute inset-0 h-full w-full" />}
      <div ref={containerRef} className="h-[420px] w-full overflow-hidden rounded-md border border-border bg-canvas" />
    </div>
  );
}
