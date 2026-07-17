import { useMemo, useState } from "react";
import { AlertTriangle, Check, Plus, Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { PLATFORM_ROLES, type AssignableRole } from "@/lib/roles";
import { CustomRoleField } from "./CustomRoleField";

const PLATFORM_GROUP = "__platform__";
const CUSTOM_GROUP = "__custom__";
const PACK_SEARCH_THRESHOLD = 6; // show the pack filter once the rail gets long

interface RoleGroup {
  key: string;
  label: string;
  kind: "platform" | "pack" | "custom";
  roles: AssignableRole[];
}

/**
 * Master-detail role picker: packs (plus a pinned Platform and Custom group) on the left,
 * the selected group's roles on the right. Only one group's roles render at a time, so the
 * list stays short no matter how many packs are onboarded. Shared by the Assign (single) and
 * Stage-access (multi) dialogs. Grouping is derived from each role's `sources` (pack@version).
 */
export function RolePicker({
  mode,
  catalog,
  selected,
  onToggle,
  onAddCustom,
  disabledIds = [],
  packTitles = {},
}: {
  mode: "single" | "multi";
  /** Full merged catalog (platform + pack + typed customs); disabled ones stay in, marked. */
  catalog: AssignableRole[];
  selected: string[];
  onToggle: (id: string) => void;
  onAddCustom: (id: string) => void;
  /** Rendered muted and non-interactive (e.g. roles the user already holds). */
  disabledIds?: string[];
  /** pack_key → human title (falls back to the pack_key when absent). */
  packTitles?: Record<string, string>;
}) {
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const disabledSet = useMemo(() => new Set(disabledIds), [disabledIds]);
  const selectedSet = useMemo(() => new Set(selected), [selected]);

  const groups = useMemo<RoleGroup[]>(() => {
    const platform: AssignableRole[] = [];
    const packMap = new Map<string, AssignableRole[]>();
    const custom: AssignableRole[] = [];
    const platformSet = new Set(PLATFORM_ROLES);

    for (const role of catalog) {
      if (platformSet.has(role.id)) {
        platform.push(role);
        continue;
      }
      const sources = role.sources ?? [];
      if (sources.length === 0) {
        custom.push(role);
        continue;
      }
      for (const src of sources) {
        const packKey = src.split("@")[0]!;
        const list = packMap.get(packKey) ?? [];
        if (!list.some((r) => r.id === role.id)) list.push(role);
        packMap.set(packKey, list);
      }
    }

    const out: RoleGroup[] = [];
    if (platform.length) out.push({ key: PLATFORM_GROUP, label: "Platform", kind: "platform", roles: platform });
    out.push(
      ...[...packMap.entries()]
        .map(([packKey, roles]) => ({
          key: packKey,
          label: packTitles[packKey] ?? packKey,
          kind: "pack" as const,
          roles,
        }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    );
    // Custom group is always present — it hosts typed custom roles and the add field.
    out.push({ key: CUSTOM_GROUP, label: "Custom role", kind: "custom", roles: custom });
    return out;
  }, [catalog, packTitles]);

  const packCount = groups.filter((g) => g.kind === "pack").length;
  const showFilter = packCount >= PACK_SEARCH_THRESHOLD;
  const visibleGroups = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return groups;
    return groups.filter((g) => g.kind !== "pack" || g.label.toLowerCase().includes(q));
  }, [groups, filter]);

  // Active group: explicit pick, else the first group holding a selectable role, else the first.
  const active =
    groups.find((g) => g.key === activeKey) ??
    groups.find((g) => g.roles.some((r) => !disabledSet.has(r.id))) ??
    groups[0];

  function countFor(g: RoleGroup): number {
    return g.roles.reduce((n, r) => n + (selectedSet.has(r.id) ? 1 : 0), 0);
  }

  return (
    <div className="grid overflow-hidden rounded-lg border border-border md:grid-cols-[210px_1fr]">
      {/* master — pack rail */}
      <aside className="flex max-h-72 flex-col border-b border-border bg-muted/30 md:max-h-80 md:border-b-0 md:border-r">
        {showFilter && (
          <div className="border-b border-border p-1.5">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter packs"
                className="h-8 pl-7 text-xs"
                aria-label="Filter packs"
              />
            </div>
          </div>
        )}
        <ul className="flex-1 overflow-y-auto p-1.5">
          {visibleGroups.map((g) => {
            const count = countFor(g);
            const isActive = active?.key === g.key;
            const allGranted =
              g.kind !== "custom" && g.roles.length > 0 && g.roles.every((r) => disabledSet.has(r.id));
            return (
              <li key={g.key}>
                <button
                  type="button"
                  onClick={() => setActiveKey(g.key)}
                  aria-current={isActive}
                  className={cn(
                    "flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-2 text-left text-sm transition-colors",
                    isActive ? "bg-background font-medium shadow-sm" : "hover:bg-background/60",
                  )}
                >
                  <span className="flex min-w-0 items-center gap-1.5">
                    {g.kind === "custom" && <Plus className="size-3.5 shrink-0 text-muted-foreground" />}
                    <span className="truncate">{g.label}</span>
                  </span>
                  {count > 0 ? (
                    <span className="shrink-0 rounded-full bg-primary px-1.5 text-xs font-medium tabular-nums text-primary-foreground">
                      {count}
                    </span>
                  ) : allGranted ? (
                    <span className="shrink-0 text-xs text-muted-foreground">granted</span>
                  ) : null}
                </button>
              </li>
            );
          })}
        </ul>
      </aside>

      {/* detail — the active group's roles */}
      <div className="min-h-[12rem] space-y-2 overflow-y-auto p-2.5 md:max-h-80">
        {active?.roles.map((role) => (
          <RoleCard
            key={role.id}
            role={role}
            mode={mode}
            checked={selectedSet.has(role.id)}
            disabled={disabledSet.has(role.id)}
            onToggle={() => onToggle(role.id)}
          />
        ))}
        {active?.kind === "custom" && (
          <CustomRoleField knownIds={[...catalog.map((r) => r.id), ...disabledIds]} onAdd={onAddCustom} />
        )}
        {active && active.kind !== "custom" && active.roles.length === 0 && (
          <p className="p-2 text-sm text-muted-foreground">This pack references no assignable roles.</p>
        )}
      </div>
    </div>
  );
}

function RoleCard({
  role,
  mode,
  checked,
  disabled,
  onToggle,
}: {
  role: AssignableRole;
  mode: "single" | "multi";
  checked: boolean;
  disabled: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      role={mode === "single" ? "radio" : "checkbox"}
      aria-checked={checked}
      disabled={disabled}
      onClick={onToggle}
      className={cn(
        "flex w-full items-start gap-3 rounded-lg border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        disabled
          ? "cursor-not-allowed border-border opacity-60"
          : checked
            ? "border-primary bg-accent/50"
            : "border-border hover:bg-accent/40",
      )}
    >
      <span
        className={cn(
          "mt-0.5 flex size-4 shrink-0 items-center justify-center border",
          mode === "single" ? "rounded-full" : "rounded",
          checked ? "border-primary bg-primary text-primary-foreground" : "border-input",
        )}
      >
        {checked && <Check className="size-3" />}
      </span>
      <span className="min-w-0 space-y-0.5">
        <span className="flex flex-wrap items-center gap-2 text-sm font-medium">
          {role.label}
          {role.isAdmin && (
            <span className="inline-flex items-center gap-1 rounded-full bg-attention-muted px-1.5 py-0.5 text-xs font-medium text-attention">
              <AlertTriangle className="size-3" /> Elevated
            </span>
          )}
          {disabled && <span className="text-xs font-normal text-muted-foreground">· granted</span>}
        </span>
        {role.description && <span className="block text-xs text-muted-foreground">{role.description}</span>}
      </span>
    </button>
  );
}
