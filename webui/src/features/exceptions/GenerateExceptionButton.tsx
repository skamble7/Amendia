import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { generateException } from "@/api/services/stub";

const REASON_CODES = ["AC01", "AC04", "RC01", "BE04"] as const;

/**
 * "Generate exception (via stub source)" — the legitimate entry point for
 * creating data in this environment. Calls the real stub_exception_generator,
 * which persists to Mongo and publishes real events. Always visible.
 */
export function GenerateExceptionButton() {
  const qc = useQueryClient();
  const [reason, setReason] = useState<(typeof REASON_CODES)[number]>("AC01");
  const [busy, setBusy] = useState(false);

  async function generate() {
    setBusy(true);
    try {
      const res = await generateException({ reason_code: reason, count: 1 } as never);
      const id = (res as any)?.created?.[0]?.exception?.exception_id;
      toast.success(id ? `Generated ${id} (${reason})` : "Exception generated");
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
        value={reason}
        onChange={(e) => setReason(e.target.value as (typeof REASON_CODES)[number])}
        className="h-8 rounded-md border border-input bg-transparent px-2 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {REASON_CODES.map((c) => (
          <option key={c} value={c}>{c}</option>
        ))}
      </select>
      <Button size="sm" onClick={generate} disabled={busy}>
        <Sparkles className="size-4" /> Generate exception (via stub source)
      </Button>
    </div>
  );
}
