import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { PageHeader } from "@/app/AppShell";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusChip, IdMono, LiveDot, EmptyState } from "@/components/primitives";
import { ConnectivityState } from "@/components/ConnectivityState";
import { isConnectivityError } from "@/api/client";
import { formatRelative } from "@/lib/format";
import { useIngestions } from "./queries";
import { GenerateExceptionButton } from "./GenerateExceptionButton";

const STATUS_OPTIONS = ["", "received", "dispatched", "accepted", "rejected", "no_process"].map((v) => ({
  value: v,
  label: v ? v.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()) : "All statuses",
}));

export function ExceptionsPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState("");
  const { data: ingestions, isLoading, isFetching, error } = useIngestions(status ? { status } : {});

  const rows = useMemo(
    () => [...(ingestions ?? [])].sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? "")),
    [ingestions],
  );

  return (
    <>
      <PageHeader
        title="Exceptions"
        description="Payment exceptions and their ingestion lifecycle."
        badge={isFetching ? <LiveDot /> : undefined}
        actions={
          <div className="flex items-center gap-2">
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="h-8 rounded-md border border-input bg-transparent px-2 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {STATUS_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <GenerateExceptionButton />
          </div>
        }
      />

      {isConnectivityError(error) ? (
        <ConnectivityState error={error} />
      ) : (
      <div className="rounded-lg border border-border bg-surface">
        {isLoading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}</div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<AlertTriangle className="size-6" />}
            title="No exceptions yet"
            description="Generate one from the stub source to see the pipeline run."
            action={<GenerateExceptionButton />}
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Exception</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Resolved pack</TableHead>
                <TableHead>Instance</TableHead>
                <TableHead>Updated</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((ing) => (
                <TableRow
                  key={ing.exception_id}
                  className="cursor-pointer"
                  tabIndex={0}
                  onClick={() => navigate(`/exceptions/${ing.exception_id}`)}
                  onKeyDown={(e) => e.key === "Enter" && navigate(`/exceptions/${ing.exception_id}`)}
                >
                  <TableCell><IdMono value={ing.exception_id} className="text-foreground" /></TableCell>
                  <TableCell className="text-sm">{ing.exception_type}</TableCell>
                  <TableCell><StatusChip kind="ingestion" value={ing.status} /></TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {ing.resolution ? `${ing.resolution.pack_key}@${ing.resolution.pack_version}` : "—"}
                  </TableCell>
                  <TableCell>{ing.process_instance_id ? <IdMono value={ing.process_instance_id} /> : <span className="text-sm text-muted-foreground">—</span>}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">{formatRelative(ing.updated_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
      )}
    </>
  );
}
