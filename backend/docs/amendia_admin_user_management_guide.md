# Amendia — User Management Guide (for Platform Administrators)

**Version:** 1.0 (matches webui v0.3 — Administration release, ADR-014)
**Audience:** holders of `role.platform.admin` — the people who control who can do what in Amendia.
**Companions:** the [Amendia User Guide](Amendia_User_Guide.md) (the platform generally), [`amendia_services_reference.md`](amendia_services_reference.md) §5 (the identity API, for anything still API-only), and the [Persona Map](amendia_persona_map.md) (the Alex profile).

---

## 1. What you are administering — the mental model

Three things exist, and keeping them distinct explains every behavior you'll see:

**Identity** — *who someone is*, proven by your organization's identity provider (Entra ID, Okta; Keycloak in dev). Passwords, MFA, and login policies live **there**, never in Amendia. Amendia only learns "this authenticated person is (issuer, subject)."

**Account** — Amendia's durable record of that person: a `usr-…` id, display name, email, linked identities, and a status (active/disabled). Accounts are created **automatically on first sign-in** (JIT provisioning) — you never create a user by hand, and there is deliberately no "delete user": history must stay attributable forever, so the off-switch is *disable*, not erase.

**Roles** — what the account may do, owned entirely by Amendia (never imported from the IdP). A person with an account but no roles can sign in and do nothing — a real and intended state.

One sentence to internalize: **the IdP decides who gets in the door; you decide what they can touch once inside.**

### The roles you can grant

The grantable list is **not fixed** — it is built from what your active process packs actually use, so it
grows as you onboard packs (see ADR-026). Two sources feed the role picker:

- **The two platform roles**, fixed by the platform itself:

  | Role | Grants | Grant with care because… |
  |---|---|---|
  | `role.process.owner` | Onboard, validate, activate, and deprecate process packs; register capabilities and artifact schemas | Activation changes how live exceptions are handled |
  | `role.platform.admin` | Everything in this guide | An admin can grant any role, including this one — treat it like a keys-to-the-keys role |

- **Roles contributed by active packs.** Every role a pack references at a human/HITL gate becomes grantable
  the moment that pack is active — no configuration on your side. In the seeded payments pack these are
  `role.payments.ops_analyst` (claims/decides analyst gates — reviews, RFIs, edit-and-approve; their edits
  enter the audit record) and `role.payments.ops_approver` (approves results and **authorizes side-effectful
  actions** — the money-moving signature four-eyes depends on). A pack that introduces, say,
  `role.lending.underwriter` simply appears in the picker once activated. Each pack role can carry a
  human-friendly **label and description** the process owner authored during onboarding (otherwise a sensible
  name is derived from the id).

The picker is a **master-detail** view: pick a pack (or the *Platform* group) on the left, then a role on the
right — so the list stays short no matter how many packs you run. There is also a **custom-role** field for
granting a role a not-yet-active pack references (it moves into its pack's group once the pack goes live).

Roles compose freely: one person may hold several (in dev, priya is process owner *and* admin). Note what roles do **not** override: an approver who also drafted a repair is still SoD-blocked from approving it — separation of duties is computed per process instance from who actually acted, and no role, including yours, bypasses it.

## 2. Where you work

**Administration → Users** in the left navigation (visible only to platform admins). Two tabs:

- **Users** — everyone who has signed in at least once. Search by name/email; filter by status, role, or **no roles** (your most useful filter — people waiting for access).
- **Pending access** — role grants staged **by email** for people who have *not* signed in yet. The moment that email authenticates for the first time, the staged roles attach automatically.

Everything you do here is recorded with your identity and a timestamp (`assigned by · at` on every role row, `staged by · at` on every pending entry).

## 3. The workflows

### 3.1 Onboard a new employee before day one

Pending access tab → **Stage access** → their work email (exactly as the IdP will present it) → pick roles (the same pack/Platform master-detail picker as §3.2; multi-select here) → confirm. Done: on their first sign-in they land in a working app with the right screens. If you typo the email, the staging simply never matches — edit or remove it from the same tab. If the email already belongs to a provisioned user, the dialog redirects you to that user's detail instead (stage nothing; assign directly).

### 3.2 Grant access to someone who already signed in

The "I logged in but the screen says I have no roles" ticket. Users tab → filter **no roles** (or search their name) → open their detail → **Assign role** → pick a pack (or *Platform*) then a role → confirm. Roles the person already holds show as *granted*; if the pack you need isn't live yet, type its role id in the **custom-role** field. Their next page load (or a fresh sign-in) picks it up. This is the intended flow, not an error: anyone in your organization's IdP *can* authenticate; only you decide who becomes an operator.

### 3.3 Change what someone can do

User detail → revoke the old role, assign the new one. Both actions take effect within seconds. Past work is unaffected: everything they decided under the old role remains attributed to them, immutably — revoking `ops_approver` from someone does not un-approve their history (nor should it; that history is the audit record).

### 3.4 Offboard a leaver

Two switches, **both required**, in this order:

1. **Disable their IdP account** (Entra/Okta/Keycloak) — stops authentication at the source. This is your organization's IAM team's action, not Amendia's.
2. **Disable their Amendia account** — user detail → Account → Disable (state a reason; it's recorded). This is your belt-and-braces: even a still-valid token now gets 403 at every service, and any residual session is dead within seconds.

What disable does **not** do: touch their history (decisions, actor-log entries, and attributions remain forever), release their claimed tasks automatically (check their open claims and reassign work by having another eligible user handle the re-created/escalated tasks), or affect the IdP account (step 1 is separate — skipping it leaves them authenticable, which is why it comes first).

### 3.5 Re-enable

The calm inverse: user detail → Account → Enable. Their roles are exactly as they were — disabling never strips roles, so a returning contractor resumes precisely where they left off (review whether that's appropriate before enabling).

### 3.6 First-time deployment — bootstrapping the first administrator

*(Mechanism introduced with the bootstrap-admin release; if your deployment predates it, the break-glass CLI below is the only path.)*

A fresh deployment has a chicken-and-egg problem by design: every administrative action requires `role.platform.admin`, nobody holds it yet, and there is deliberately no Amendia-side backdoor. The resolution uses the same staging mechanism as §3.1, driven by deployment configuration instead of a person:

**Primary path — bootstrap staging.** During installation, the deploying team sets the identity service's `IDENTITY_BOOTSTRAP_ADMIN_EMAILS` configuration (a comma-separated list of the bank's designated administrators' work emails, exactly as the IdP will present them). At startup the identity service converts these into pending role assignments for `role.platform.admin`, recorded as `staged_by: bootstrap`. The designated people then simply sign in through the bank's IdP — JIT provisioning creates their accounts and the staged admin role attaches, fully audited. No bypass of the IdP, no manual database work, no special first-login flow.

**Self-disarming by design:** bootstrap staging is applied **only while the deployment has zero active platform admins**. Once any admin exists, the setting is inert — it cannot re-grant admin on later restarts, cannot resurrect access for an email whose owner has left, and cannot conflict with the last-admin guardrail. Set it at install time, and after the first admin's first sign-in it is effectively documentation. Stage at least two emails (see §4's two-admin corollary).

**Recovery path — break-glass CLI.** For the situation the guardrails cannot prevent — every admin disabled at the IdP, or the sole admin's email changed — someone with **infrastructure access** runs the bootstrap command inside the identity service container (`python -m app.bootstrap_admin --email <work-email>`), which stages `role.platform.admin` for that email through the same mechanism (`staged_by: break-glass`, logged loudly). This is intentionally an infrastructure-level act: whoever can exec into your containers is already your root of trust, and the action leaves the same audit trail as everything else. Record its use in your incident/change process.

**What is deliberately not supported:** creating users or roles by writing to the database directly. It bypasses validation, auditing, and the guardrails — if you find yourself considering it, use the break-glass CLI instead.

## 4. The guardrails (and why the UI sometimes says no)

Two protections are enforced server-side and rendered as disabled controls with tooltips:

**Self-protection.** You cannot disable your own account or revoke your own `role.platform.admin`. If you genuinely need to step down, another admin does it to you — which is the point: no accidental self-lockout, and every admin change has a second person in the record.

**Last-admin protection.** The system refuses to disable or de-admin the *only remaining active* platform admin. Before offboarding an admin, ensure a successor holds the role first. (Corollary: keep at least two active admins at all times — the guardrail protects you from zero, but one is still a bus-factor.)

If a control is disabled and you believe it shouldn't be, the state may have changed under you (another admin acting concurrently) — refresh; the server's answer is authoritative.

## 5. What is still API-only (honest edges)

- **Identity re-linking** — attaching a new (issuer, subject) to an existing account, e.g. after an IdP migration, is an identity-service API operation. The account model supports it (identities are a list precisely for this); the screen doesn't exist yet.
- **Bulk operations & SCIM** — no CSV import, no automatic provisioning/deprovisioning from your IAM yet. JIT + pending access is the current onboarding path.
- **Audit browsing** — each record shows its own who/when, but there is no cross-cutting "all role changes last quarter" report yet. The data exists; the screen doesn't.

## 6. Good practice (recommended, not enforced)

Least privilege by default — stage exactly the roles the job needs, and treat `platform.admin` grants as events worth a second admin's awareness. Review the no-roles filter periodically (accounts that signed in once and were never granted anything are usually noise, occasionally a signal). Review role assignments on a cadence your compliance function likes — the assigned-by/at trail makes access reviews straightforward even without the report screen. And align disable actions with your joiner-mover-leaver process so §3.4's two switches never drift apart.

## 7. Admin troubleshooting

- **"I staged access but they say they have no roles":** the email staged must match what the IdP presents — check the user's actual email on their (now JIT-created, roleless) account in the Users tab, and assign directly there.
- **"I can't revoke this admin's role":** last-admin protection — grant `platform.admin` to a successor first — or it's your own role (self-protection).
- **A user reports 403s on screens they can see:** their roles changed mid-session in their favor's opposite; a fresh sign-in resolves the stale view. The server was never wrong — navigation is a courtesy, enforcement is per-request.
- **Someone needs access urgently and IT can't create their IdP account yet:** there is no Amendia-side bypass, by design. No IdP identity, no entry.

## 8. Changelog

- **1.2** — Roles you can grant are now **dynamic**, derived from active packs (ADR-026): reframed "The roles you can grant" (two platform roles + pack-contributed roles + custom-role field), and noted the master-detail picker in the Assign/Stage flows.
- **1.1** — Added §3.6: Day-0 bootstrap of the first administrator (`IDENTITY_BOOTSTRAP_ADMIN_EMAILS` self-disarming staging + break-glass CLI); fixed companion links; linked the persona map.
- **1.0** — First edition, covering the Administration release: users & pending-access management, role assignment, disable/enable, guardrails, and the API-only edges.

*Maintainers: this guide changes whenever the identity service or Administration screens do — same PR, same discipline as the main user guide.*
