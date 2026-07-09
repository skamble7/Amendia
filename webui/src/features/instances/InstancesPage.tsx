import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Workflow } from "lucide-react";
import { PageHeader } from "@/app/AppShell";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusChip, IdMono, LiveDot, EmptyState } from "@/components/primitives";
import { ConnectivityState } from "@/components/ConnectivityState";
import { isConnectivityError } from "@/api/client";
import { formatRelative } from "@/lib/format";
import { useInstances } from "./queries";

const STATUS_OPTIONS = ["", "running", "waiting_hitl", "completed", "failed"].map((v) => ({
  value: v,
  label: v ? v.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()) : "All statuses",
}));

export function InstancesPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState("");
  const { data: instances, isLoading, isFetching, error } = useInstances(status ? { status } : {});

  const rows = useMemo(
    () => [...(instances ?? [])].sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? "")),
    [instances],
  );

  return (
    <>
      <PageHeader
        title="Instances"
        description="Running and completed process instances."
        badge={isFetching ? <LiveDot /> : undefined}
        actions={
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="h-8 rounded-md border border-input bg-transparent px-2 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        }
      />

      {isConnectivityError(error) ? (
        <ConnectivityState error={error} />
      ) : (
      <div className="rounded-lg border border-border bg-surface">
        {isLoading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}</div>
        ) : rows.length === 0 ? (
          <EmptyState icon={<Workflow className="size-6" />} title="No instances yet" description="Instances appear when an exception is dispatched to a process pack. Generate one from Exceptions." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Instance</TableHead>
                <TableHead>Exception</TableHead>
                <TableHead>Pack</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Outcome</TableHead>
                <TableHead>Updated</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((inst) => (
                <TableRow
                  key={inst.process_instance_id}
                  className="cursor-pointer"
                  tabIndex={0}
                  onClick={() => navigate(`/instances/${inst.process_instance_id}`)}
                  onKeyDown={(e) => (e.key === "Enter") && navigate(`/instances/${inst.process_instance_id}`)}
                >
                  <TableCell><IdMono value={inst.process_instance_id} className="text-foreground" /></TableCell>
                  <TableCell><IdMono value={inst.exception_id} /></TableCell>
                  <TableCell className="text-sm">
                    {inst.pack_key} <span className="text-muted-foreground">@{inst.pack_version}</span>
                  </TableCell>
                  <TableCell><StatusChip kind="instance" value={inst.status} /></TableCell>
                  <TableCell className="text-sm text-muted-foreground">{inst.outcome ?? "—"}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">{formatRelative(inst.updated_at)}</TableCell>
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
