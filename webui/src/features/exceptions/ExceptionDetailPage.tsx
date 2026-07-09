import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Paperclip, MessageSquare, ExternalLink } from "lucide-react";
import { PageHeader } from "@/app/AppShell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusChip, IdMono, ReasonCodeBadge, EmptyState } from "@/components/primitives";
import { ConnectivityState } from "@/components/ConnectivityState";
import { isConnectivityError } from "@/api/client";
import { ExceptionSummary } from "./ExceptionSummary";
import { attachmentUrl } from "@/api/services/stub";
import { formatDateTime } from "@/lib/format";
import { statusMeta, INGESTION_STATUS } from "@/lib/status";
import { useException, useIngestion } from "./queries";

export function ExceptionDetailPage() {
  const { exceptionId } = useParams();
  const { data: exc, isLoading, error } = useException(exceptionId);
  const { data: ingestion } = useIngestion(exceptionId);

  if (isLoading) {
    return <div className="space-y-4"><Skeleton className="h-8 w-64" /><Skeleton className="h-64 w-full" /></div>;
  }
  if (isConnectivityError(error)) return <ConnectivityState error={error} />;
  if (!exc) {
    return <EmptyState title="Exception not found" description="The id may be invalid." />;
  }

  const attachments = (exc as any).attachments ?? [];
  const related = (exc as any).related_messages ?? [];
  const history = ingestion?.status_history ?? [];

  return (
    <>
      <div className="mb-4">
        <Link to="/exceptions" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" /> Exceptions
        </Link>
      </div>
      <PageHeader
        title={exc.exception_id}
        description={(exc as any).reason_narrative}
        actions={ingestion && <StatusChip kind="ingestion" value={ingestion.status} />}
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_340px]">
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>Payment</CardTitle></CardHeader>
            <CardContent><ExceptionSummary exc={exc} /></CardContent>
          </Card>

          <Card>
            <CardHeader className="flex-row items-center gap-2">
              <Paperclip className="size-4" /><CardTitle>Attachments</CardTitle>
            </CardHeader>
            <CardContent>
              {attachments.length === 0 ? (
                <p className="text-sm text-muted-foreground">None.</p>
              ) : (
                <ul className="space-y-1.5">
                  {attachments.map((a: any) => (
                    <li key={a.attachment_id}>
                      <a
                        href={attachmentUrl(exc.exception_id, a.attachment_id)}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-2 text-sm text-agent hover:underline"
                      >
                        <Paperclip className="size-3.5" />
                        {a.filename ?? a.attachment_id}
                        {a.content_type && <Badge variant="outline" className="text-[10px]">{a.content_type}</Badge>}
                        <ExternalLink className="size-3" />
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          {related.length > 0 && (
            <Card>
              <CardHeader className="flex-row items-center gap-2">
                <MessageSquare className="size-4" /><CardTitle>Related messages</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-1.5 text-sm">
                  {related.map((m: any, i: number) => (
                    <li key={i} className="flex items-center gap-2">
                      {m.msg_type && <Badge variant="outline" className="font-mono text-[10px]">{m.msg_type}</Badge>}
                      <span className="text-muted-foreground">{m.reference ?? m.case_id ?? JSON.stringify(m)}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>Reason codes</CardTitle></CardHeader>
            <CardContent className="flex flex-wrap gap-1.5">
              {((exc as any).reason_codes ?? []).map((r: string) => <ReasonCodeBadge key={r} code={r} />)}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Journey</CardTitle></CardHeader>
            <CardContent>
              <ol className="space-y-3">
                {history.map((h: any, i: number) => {
                  const meta = statusMeta(INGESTION_STATUS, h.status);
                  return (
                    <li key={i} className="flex items-start gap-3">
                      <span className="mt-1 flex size-2 shrink-0 rounded-full bg-agent" />
                      <div>
                        <p className="text-sm font-medium">{meta.label}</p>
                        <p className="text-xs text-muted-foreground">{formatDateTime(h.at)}</p>
                        {h.detail && <p className="text-xs text-muted-foreground">{h.detail}</p>}
                      </div>
                    </li>
                  );
                })}
              </ol>
              {ingestion?.process_instance_id && (
                <Link
                  to={`/instances/${ingestion.process_instance_id}`}
                  className="mt-3 inline-flex items-center gap-1 text-sm text-agent hover:underline"
                >
                  View instance <IdMono value={ingestion.process_instance_id} /> <ExternalLink className="size-3" />
                </Link>
              )}
              {ingestion?.status === "no_process" && (
                <p className="mt-3 text-sm text-danger">No active process pack matched this exception.</p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}
