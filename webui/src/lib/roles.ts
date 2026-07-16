/**
 * Amendia `role.*` vocabulary (mirrors the platform contracts / identity seed).
 * Roles are plain strings from `GET /me` — never parsed from the token. These are
 * the ids the UI keys progressive disclosure off (the backend still enforces).
 */
export const ROLE = {
  analyst: "role.payments.ops_analyst",
  approver: "role.payments.ops_approver",
  processOwner: "role.process.owner",
  platformAdmin: "role.platform.admin",
} as const;

export type RoleId = string;

/**
 * Roles that make someone an *operator* (they work the payment-exception flow). The
 * operator nav entries (dashboard / inbox / instances / exceptions) are shown to any
 * of these — so a platform-admin-*only* user (e.g. alex) sees just Administration,
 * while every existing operator persona's nav is unchanged (analyst / approver /
 * process-owner all remain operators). Reads themselves stay role-free server-side;
 * this is purely progressive-disclosure of the nav.
 */
export const OPERATOR_ROLES: string[] = [
  ROLE.analyst,
  ROLE.approver,
  ROLE.processOwner,
];

const ROLE_LABEL: Record<string, string> = {
  [ROLE.analyst]: "Analyst",
  [ROLE.approver]: "Approver",
  [ROLE.processOwner]: "Process owner",
  [ROLE.platformAdmin]: "Platform admin",
};

/** Shape guard for a `role.*` id (mirrors backend `ROLE_ID_RE`). */
const ROLE_ID_RE = /^role\.[a-z0-9_.]+$/;
export function isValidRoleId(role: string): boolean {
  return ROLE_ID_RE.test(role);
}

/** Fallback label for a role with no curated/authored name: last dotted segment, Title Cased. */
export function humanizeRole(role: string): string {
  const tail = role.split(".").pop() ?? role;
  const label = tail.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return label || role;
}

export function roleLabel(role: string | null | undefined): string {
  if (!role) return "—";
  return ROLE_LABEL[role] ?? humanizeRole(role);
}

/** Short, comma-joined labels for a role set (top-bar chip). */
export function rolesSummary(roles: string[]): string {
  if (!roles.length) return "No roles";
  return roles.map(roleLabel).join(" · ");
}

/** Plain-language, admin-facing descriptions (shown on role rows + assign cards). */
export const ROLE_DESCRIPTION: Record<string, string> = {
  [ROLE.analyst]: "Reviews assessments and drafts repairs and returns at analyst gates.",
  [ROLE.approver]: "Approves results and authorizes payment actions at approver gates.",
  [ROLE.processOwner]: "Authors, validates, and activates process packs in the Registry.",
  [ROLE.platformAdmin]:
    "Full administrative control: manages users, roles, and staged access across the platform.",
};

export function roleDescription(role: string): string {
  return ROLE_DESCRIPTION[role] ?? "";
}

/**
 * The two genuinely code-fixed platform roles (enforced by static route guards, not by any
 * pack). They are always assignable regardless of what packs reference, so the admin picker
 * merges them in even when the roles-in-use query is empty or still loading.
 */
export const PLATFORM_ROLES: string[] = [ROLE.processOwner, ROLE.platformAdmin];

/** One entry the admin role picker renders (a merge of platform roles + pack roles in use). */
export interface AssignableRole {
  id: string;
  label: string;
  description: string;
  isAdmin: boolean;
  /** pack_key@version references, for pack-local roles (absent/empty for platform roles). */
  sources?: string[];
}

/** Minimal shape of the `GET /roles` rows (see `RoleInUse` in the registry service). */
export interface RoleInUseLike {
  role_id: string;
  label?: string | null;
  description?: string | null;
  sources?: string[];
}

/**
 * Build the assignable-role catalog for the admin dialogs: the code-fixed {@link PLATFORM_ROLES}
 * unioned with the roles active packs actually reference (from `GET /roles`), deduped by id.
 * Labels/descriptions prefer the endpoint's authored metadata, then the curated platform maps,
 * then a humanized fallback — so a brand-new pack role is assignable with a sensible name even
 * before anyone authors metadata for it.
 */
export function buildAssignableRoles(rolesInUse: RoleInUseLike[]): AssignableRole[] {
  const out: AssignableRole[] = [];
  const seen = new Set<string>();

  const push = (id: string, authored?: RoleInUseLike) => {
    if (seen.has(id)) return;
    seen.add(id);
    out.push({
      id,
      label: authored?.label || ROLE_LABEL[id] || humanizeRole(id),
      description: authored?.description || ROLE_DESCRIPTION[id] || "",
      isAdmin: isAdminRole(id),
      sources: authored?.sources && authored.sources.length ? authored.sources : undefined,
    });
  };

  // Platform roles first (curated, disclosure order), then pack roles in use.
  for (const id of PLATFORM_ROLES) push(id);
  for (const r of rolesInUse) push(r.role_id, r);
  return out;
}

/** True for the elevated platform-admin role — drives caution treatment. */
export function isAdminRole(role: string): boolean {
  return role === ROLE.platformAdmin;
}

/**
 * Badge variant per role. `platform admin` is rendered with the amber "attention"
 * treatment so it reads as an elevated, handle-with-care grant; the operating roles
 * are neutral outlines.
 */
export function roleBadgeVariant(role: string): "attention" | "outline" {
  return isAdminRole(role) ? "attention" : "outline";
}
