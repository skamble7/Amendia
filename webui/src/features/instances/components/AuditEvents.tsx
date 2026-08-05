import { ScrollText } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatDateTime } from "@/lib/format";
import type { InstanceAuditOut } from "@/api/types";

/** The append-only audit events for the instance (ADR-058 §5). Null → a graceful note. */
export function AuditEvents({ audit }: { audit: InstanceAuditOut | null | undefined }) {
  const events = audit?.events ?? [];
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2">
          <ScrollText className="size-4" /> Audit events
        </CardTitle>
        {audit ? <span className="text-xs text-muted-foreground">{audit.count} rows</span> : null}
      </CardHeader>
      <CardContent>
        {!audit ? (
          <p className="text-sm text-muted-foreground">Audit trail unavailable (glea-service not reachable).</p>
        ) : events.length === 0 ? (
          <p className="text-sm text-muted-foreground">No audit events recorded for this instance.</p>
        ) : (
          <ol className="space-y-2">
            {events.map((e) => (
              <li key={e.event_id} className="flex items-start gap-2 text-sm">
                <Badge variant="outline" className="shrink-0">
                  {e.kind}
                </Badge>
                <div className="min-w-0 flex-1">
                  <p className="truncate">
                    {e.element_id || e.actor || e.kind}
                    {e.decision ? ` · ${e.decision}` : ""}
                    {e.egress_decision ? ` · egress ${e.egress_decision}` : ""}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {e.actor || e.decided_by || "—"}
                    {e.role ? ` · ${e.role}` : ""} · {formatDateTime(e.occurred_at)}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}
