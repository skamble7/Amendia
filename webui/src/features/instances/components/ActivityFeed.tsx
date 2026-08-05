import { Badge } from "@/components/ui/badge";
import { ActorAvatar } from "@/components/primitives";
import { formatDateTime } from "@/lib/format";
import type { ActorLogEntry } from "@/api/types";

interface Props {
  entries: ActorLogEntry[];
  roleByElement: Map<string, string>;
  rationaleByElement: Map<string, string>;
  onViewTrace?: (elementId: string) => void;
}

/** The actor log as a newest-first activity feed (ADR-058 Phase E), enriched with the human role (from
 * the decision trail) and the agent rationale (Phase C) where present. Core view — always renders. */
export function ActivityFeed({ entries, roleByElement, rationaleByElement, onViewTrace }: Props) {
  const items = entries.map((e, i) => ({ e, i })).reverse(); // newest first, stable keys
  return (
    <ol className="space-y-3">
      {items.map(({ e, i }) => {
        const role = e.kind === "human" ? roleByElement.get(e.element_id) : undefined;
        const rationale = rationaleByElement.get(e.element_id);
        return (
          <li key={i} className="flex items-start gap-3 border-b border-border pb-3 last:border-none last:pb-0">
            <ActorAvatar actor={e.actor} kind={e.kind} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-medium">{e.element_id}</p>
                {role ? <Badge variant="outline">{role}</Badge> : null}
              </div>
              <p className="text-xs text-muted-foreground">
                {e.kind === "capability" ? "Agent" : "Human"} · {e.actor} · {formatDateTime(e.at)}
              </p>
              {rationale ? (
                <p className="mt-1.5 rounded-md border-l-2 border-agent/50 bg-surface/60 px-2.5 py-1.5 text-xs text-muted-foreground">
                  <span className="mb-0.5 block text-[10px] uppercase tracking-wide text-muted-foreground/80">
                    rationale
                  </span>
                  {rationale.length > 200 ? `${rationale.slice(0, 199)}…` : rationale}
                </p>
              ) : null}
            </div>
            {onViewTrace ? (
              <button
                type="button"
                onClick={() => onViewTrace(e.element_id)}
                className="shrink-0 text-xs text-muted-foreground hover:text-foreground"
              >
                View trace
              </button>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
