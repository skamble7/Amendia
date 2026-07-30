import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useApiQuery } from "@/api/live";
import { listGenerators, generateTrigger, type Generator } from "@/api/services/stub";

const selectCls =
  "h-8 rounded-md border border-input bg-transparent px-2 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50";

/**
 * "Generate trigger (via stub source)" — the legitimate entry point for creating data in this environment.
 * Domain-neutral: it discovers the available trigger sources + scenarios from the stub's `/generators` catalog
 * and POSTs the chosen scenario to that generator's own endpoint. No domain literals (reason codes, ticket
 * flags) live here. If the catalog can't load, the control disables with a "stub unreachable" tooltip.
 */
export function GenerateExceptionButton() {
  const qc = useQueryClient();
  const { data, error } = useApiQuery(["generators"], (signal) => listGenerators(signal));
  const generators: Generator[] = data?.generators ?? [];

  const [sourceId, setSourceId] = useState<string>("");
  const [scenarioId, setScenarioId] = useState<string>("");
  const [busy, setBusy] = useState(false);

  // Default the selects once the catalog arrives (first source, its first scenario); keep them valid as the
  // source changes.
  useEffect(() => {
    if (!generators.length) return;
    const src = generators.find((g) => g.id === sourceId) ?? generators[0]!;
    if (src.id !== sourceId) setSourceId(src.id);
    if (!src.scenarios.some((s) => s.id === scenarioId)) setScenarioId(src.scenarios[0]?.id ?? "");
  }, [generators, sourceId, scenarioId]);

  const source = generators.find((g) => g.id === sourceId);
  const scenario = source?.scenarios.find((s) => s.id === scenarioId);

  if (error) {
    return (
      <Button size="sm" disabled title="stub unreachable — cannot load trigger generators">
        <Sparkles className="size-4" /> Generate trigger (via stub source)
      </Button>
    );
  }

  async function generate() {
    if (!source || !scenario) return;
    setBusy(true);
    try {
      const res = await generateTrigger(source.endpoint, scenario.body);
      const created = res?.created?.[0];
      const id = created?.exception?.exception_id ?? created?.ticket?.ticket_id;
      toast.success(id ? `Generated ${id} (${scenario.label})` : "Trigger generated");
      qc.invalidateQueries({ queryKey: ["ingestions"] });
      qc.invalidateQueries({ queryKey: ["instances"] });
    } catch {
      /* client.ts already surfaced the error toast */
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <select
        aria-label="Trigger source"
        value={sourceId}
        onChange={(e) => setSourceId(e.target.value)}
        disabled={!generators.length}
        className={selectCls}
      >
        {generators.map((g) => <option key={g.id} value={g.id}>{g.label}</option>)}
      </select>
      <select
        aria-label="Scenario"
        value={scenarioId}
        onChange={(e) => setScenarioId(e.target.value)}
        disabled={!source?.scenarios.length}
        className={selectCls}
      >
        {(source?.scenarios ?? []).map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
      </select>
      <Button size="sm" onClick={generate} disabled={busy || !scenario}>
        <Sparkles className="size-4" /> Generate trigger (via stub source)
      </Button>
    </div>
  );
}
