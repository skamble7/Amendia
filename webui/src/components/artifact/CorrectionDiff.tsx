import { ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";

/** before → after diff row, used by the repair correction custom renderers. */
export function DiffRow({ field, before, after }: { field: string; before: unknown; after: unknown }) {
  return (
    <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 rounded-md border border-border bg-surface/60 p-2 text-sm">
      <div className="min-w-0">
        <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{field}</p>
        <p className="truncate font-mono tabular-nums text-danger line-through decoration-danger/50">{String(before)}</p>
      </div>
      <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 text-right">
        <p className="text-[11px] uppercase tracking-wide text-muted-foreground">proposed</p>
        <p className="truncate font-mono tabular-nums text-success">{String(after)}</p>
      </div>
    </div>
  );
}

export function DiffList({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cn("space-y-2", className)}>{children}</div>;
}
