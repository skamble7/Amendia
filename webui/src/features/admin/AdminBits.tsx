import { useState } from "react";
import { Check, Copy, ShieldCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { isAdminRole, roleBadgeVariant, roleLabel } from "@/lib/roles";

/** A role rendered as a badge; the elevated platform-admin role is set apart. */
export function RoleBadge({ role, className }: { role: string; className?: string }) {
  const admin = isAdminRole(role);
  return (
    <Badge variant={roleBadgeVariant(role)} className={className}>
      {admin && <ShieldCheck className="size-3" />}
      {roleLabel(role)}
    </Badge>
  );
}

/** Account status chip — active reads calm/positive, disabled reads muted. */
export function UserStatusBadge({ status }: { status: string }) {
  if (status === "disabled") {
    return (
      <Badge variant="outline" className="text-muted-foreground">
        Disabled
      </Badge>
    );
  }
  return <Badge variant="success">Active</Badge>;
}

/** Monospaced id with a copy affordance (usr-…, emails). */
export function CopyableId({ value, className }: { value: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(value);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1200);
      }}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 font-mono text-xs tabular-nums text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
      title="Copy to clipboard"
    >
      {value}
      {copied ? <Check className="size-3 text-success" /> : <Copy className="size-3" />}
    </button>
  );
}
