import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

export function CommentField({
  value,
  onChange,
  required,
  id = "decision-comment",
}: {
  value: string;
  onChange: (v: string) => void;
  required?: boolean;
  id?: string;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="flex items-center gap-1">
        Comment {required && <span className="text-danger">*</span>}
      </Label>
      <Textarea
        id={id}
        rows={2}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={required ? "A comment is required for this decision." : "Optional context for the audit trail."}
      />
    </div>
  );
}

export function DecisionRow({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cn("flex flex-wrap items-center justify-end gap-2 pt-1", className)}>{children}</div>;
}
