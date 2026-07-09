import { ArrowRight } from "lucide-react";
import { AmountDisplay, ReasonCodeBadge, IdMono } from "@/components/primitives";
import { shortId } from "@/lib/format";
import type { StoredException } from "@/api/types";

/** Extract the display payment summary from a StoredException envelope. */
export function paymentSummary(exc: StoredException | undefined | null) {
  const p = (exc as any)?.payment ?? {};
  const amt = p.settlement_amount ?? {};
  return {
    amount: amt.value as number | undefined,
    currency: amt.currency as string | undefined,
    msgType: p.msg_type as string | undefined,
    uetr: p.uetr as string | undefined,
    debtor: p.debtor?.name as string | undefined,
    creditor: p.creditor?.name as string | undefined,
    debtorAgent: p.debtor_agent?.bic as string | undefined,
    creditorAgent: p.creditor_agent?.bic as string | undefined,
    creditorAccount: p.creditor?.account?.id as string | undefined,
  };
}

/** Compact exception summary (used in the task context rail and elsewhere). */
export function ExceptionSummary({ exc }: { exc: StoredException | null | undefined }) {
  const s = paymentSummary(exc);
  const reasons = (exc as any)?.reason_codes ?? [];
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <IdMono value={exc?.exception_id} className="text-sm" />
        <div className="flex gap-1">
          {reasons.map((r: string) => (
            <ReasonCodeBadge key={r} code={r} />
          ))}
        </div>
      </div>
      <div>
        <AmountDisplay amount={s.amount} currency={s.currency} className="text-lg" />
        {s.msgType && <p className="text-xs text-muted-foreground">{s.msgType}</p>}
      </div>
      <div className="flex items-center gap-2 text-sm">
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">{s.debtor ?? "—"}</p>
          <p className="text-xs text-muted-foreground">{s.debtorAgent}</p>
        </div>
        <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1 text-right">
          <p className="truncate font-medium">{s.creditor ?? "—"}</p>
          <p className="text-xs text-muted-foreground">{s.creditorAgent}</p>
        </div>
      </div>
      {s.uetr && (
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted-foreground">UETR</span>
          <IdMono value={shortId(s.uetr, 10, 6)} />
        </div>
      )}
    </div>
  );
}
