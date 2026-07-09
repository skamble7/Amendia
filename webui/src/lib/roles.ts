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

export function roleLabel(role: string | null | undefined): string {
  if (!role) return "—";
  return ROLE_LABEL[role] ?? role;
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

/** Roles an admin can assign, in disclosure order (elevated role last). */
export const ASSIGNABLE_ROLES: string[] = [
  ROLE.analyst,
  ROLE.approver,
  ROLE.processOwner,
  ROLE.platformAdmin,
];

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
