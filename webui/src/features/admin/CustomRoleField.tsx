import { useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { isValidRoleId } from "@/lib/roles";

/**
 * Free-text entry for a `role.*` id that isn't (yet) referenced by any active pack — so an
 * admin can grant a brand-new pack's role before the pack activates. Validated against the
 * same shape regex the backend enforces; `onAdd` receives a well-formed, non-duplicate id.
 */
export function CustomRoleField({
  knownIds,
  onAdd,
}: {
  knownIds: string[];
  onAdd: (roleId: string) => void;
}) {
  const [value, setValue] = useState("");
  const trimmed = value.trim();
  const shapeOk = isValidRoleId(trimmed);
  const duplicate = knownIds.includes(trimmed);
  const error = trimmed && !shapeOk ? "Must look like role.<domain>.<name> (lowercase)." : "";
  const canAdd = shapeOk && !duplicate;

  function add() {
    if (!canAdd) return;
    onAdd(trimmed);
    setValue("");
  }

  return (
    <div className="space-y-1.5">
      <Label htmlFor="custom-role">Custom role</Label>
      <div className="flex items-start gap-2">
        <div className="flex-1 space-y-1">
          <Input
            id="custom-role"
            placeholder="role.lending.underwriter"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                add();
              }
            }}
            autoComplete="off"
            aria-invalid={!!error}
          />
          {error && <p className="text-xs text-destructive">{error}</p>}
          {duplicate && trimmed && (
            <p className="text-xs text-muted-foreground">That role is already listed above.</p>
          )}
        </div>
        <Button type="button" variant="outline" size="sm" onClick={add} disabled={!canAdd}>
          <Plus className="size-3" /> Add
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        Grant a role a pack references before it&apos;s active. It appears in the list once the pack goes live.
      </p>
    </div>
  );
}
