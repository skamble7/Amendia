# Amendia webui — user guide

The operator UI for the Amendia agentic payment-exception platform: a task inbox with
the four HITL decision modes, instance and exception views, a dashboard, and the process
registry. Everything on screen comes from the live backend.

## 1. What this is

Amendia runs a bank's payment-exception processes (defined as BPMN) through an AI agent
runtime, pausing at **human decision gates**. You sign in, pick up gates assigned to your
role from the inbox, and approve / edit / reject / complete them. Your decisions are
recorded against your **Amendia identity** on immutable records.

## 2. Getting started

### Sign in

The sign-in screen has one button: **Continue with your organization**. It starts a
standard OIDC (Authorization Code + PKCE) redirect to your identity provider, you
authenticate there (your organization's own login and MFA), and you land back in Amendia —
on the exact page you were heading to, even a deep link into a specific task.

- **In production**, that button goes to your bank's own IAM (Microsoft Entra ID, Okta,
  Ping, any certified OIDC provider) — Amendia never sees your password, and your
  organization's login policies and MFA apply.
- **In local dev**, it goes to the bundled Keycloak. Sign in as one of the three dev users:

  | User | Username | Role(s) |
  |---|---|---|
  | Riya Sharma | `riya` | Payments Ops Analyst |
  | Marcus Bianchi | `marcus` | Payments Ops Approver |
  | Priya Nair | `priya` | Process Owner + Platform Admin |
  | Alex Okafor | `alex` | Platform Admin (only) |
  | Sam Delgado | `sam` | *(none — first sign-in lands in the "no access yet" state)* |

  Password for all five: `dev-password` (**dev only** — see the Keycloak README). Sign in as **alex**
  to see the Administration area on its own (no operator screens); sign in as **sam** to see what a
  brand-new user with no roles gets.

Your name and roles in the top bar come from Amendia's own identity service (`GET /me`),
not from the login token — Amendia decides what you can do, your IdP only proves who you are.

The top-bar user menu also holds a **theme** control — Light / Dark / System. Your choice is
remembered on this device; **System** follows your operating system's appearance live.

### Switching personas (dev)

There is **no user switcher** — that was the old development placeholder. To act as a
different persona (e.g. an analyst drafts a repair, then an approver authorizes it, which
separation-of-duties requires be different people), **sign out and sign in as the other
user**. This is the same flow a real operator uses, so what you see in dev is honest.

### Do the work

1. Open the app and sign in (as **riya** for the analyst gates).
2. Go to **Exceptions → Generate exception (via stub source)** and pick a reason code
   (`AC01`). This calls the real stub, which publishes a real event; an instance starts.
3. Its gates appear in the **Task inbox**. Open one, **Claim** it, and record a decision.
4. When a gate needs the approver role, sign out and sign in as **marcus**.

Registry (process authoring) is only visible to **Priya** (the process owner).

## 3. The task inbox & gates

Each gate shows its HITL mode (Review, Approve result, Authorize actions, Manual), the
required role, SLA, and assignee. A **lock icon** means you can't act on it — either it
needs a role you don't hold, or **separation of duties** excludes you (you already acted on
a conflicting step); the tooltip explains which. These are progressive-disclosure hints —
the backend enforces the same rules, so a lock you somehow bypass still fails server-side
with the reason shown.

## 4. Instances, exceptions, dashboard

- **Instances** — every running/finished process, its outcome, artifacts, and actor log
  (decisions show the acting Amendia user id).
- **Exceptions** — the payment parties and the exception's journey from raised to resolved.
- **Dashboard** — the live operational overview.

## 5. Registry (process owners)

**Registry → Onboard pack** walks Manifest → BPMN → Validate → Activate against the real
registry, with the validation report grouped by validator stage. Activation is blocked while
any stage reports an error. Visible only to users with the process-owner role.

## 6. Administration — Users (platform admins)

**Administration → Users** is visible only to users with `role.platform.admin` (same
progressive-disclosure mechanism as Registry). It is where the platform administrator manages
who exists and what they can do. For the full admin playbook (onboarding, offboarding, guardrails,
API-only edges) see the [User Management Guide](../backend/docs/amendia_admin_user_management_guide.md);
the Alex persona is profiled in §10. Two tabs:

- **Users** — every provisioned user with their status, roles (platform admin stands apart),
  the identity provider they came from, and when they were first seen. Search by name / email /
  id and filter by status, by role, or by **no roles** (handy for spotting people who signed in
  but haven't been granted access yet). Disabled users are shown muted. Open a user for detail.
- **Pending access** — roles **staged by email before someone first signs in**. Each entry
  shows the email, the staged roles, who staged them and when, and the note that they *activate
  on first sign-in*. Stage new access, edit the staged roles, or remove an entry.

**User detail** has three blocks:

- **Roles** — each assigned role with a plain-language description and who assigned it/when;
  **Assign role** opens a picker with descriptions (platform admin is flagged as elevated);
  revoke from any row. A user with no roles shows an inline "assign a role" prompt.
- **Identities** — the read-only `iss`/`sub` link(s) to your identity provider. Re-linking or
  merging identities is API-only in this release.
- **Account** — **Disable** (with a consequence explainer and a required reason) blocks the
  user from every Amendia service without deleting anything; **Enable** restores access.

**Guardrails.** The UI disables the controls that would break the platform and explains why on
hover, and the server enforces the same rules regardless of the UI:

- You **cannot disable your own account** or **revoke your own** platform-admin role
  (`self_protection`).
- You **cannot remove the last active platform admin** — revoking or disabling the only
  remaining one is refused (`last_admin`).

**Staging an email that already exists.** If you stage access for an email that already belongs
to a provisioned user, the request is refused and the dialog offers a jump to that user's detail
page — assign the roles there instead.

## 7. Current limitations

- **Session hardening isn't configured.** Idle-timeout / step-up policies beyond the IdP's
  own token lifetimes aren't set up.
- **Identity re-linking is API-only.** Merging or re-pointing a user's `iss`/`sub` identities
  (e.g. after an IdP migration) is done through the identity service's API; there is no UI for it.
- **Live updates poll.** Inbox and instance status refresh on an interval; the push
  (SSE/notification-service) fan-out is a later step.
- **No parallel gateways / timers.** The executed process is linear (the reference pack was
  linearized); parallel branches, timers, and escalation are out of the supported subset.

## 8. Changelog

- **0.3 — Administration UI, roleless state, and light mode.** A platform-admin **Administration
  → Users** area (users list with a pending-access tab, user detail, assign-role and stage-access
  dialogs, self/last-admin guardrails). A calm **"no access yet"** full-page state for users who
  sign in with zero roles (replacing the old empty-dashboard-with-403s behaviour). A working
  **theme toggle** (Light / Dark / System) in the user menu, applied before first paint.
- **0.2 — Real OIDC sign-in (PKCE); dev user-switcher retired; decisions recorded against
  authenticated identities.** Identity and roles now come from `GET /me`; the top bar shows
  your real name/roles; sign out ends your IdP session.
- **0.1 —** Initial operator UI (inbox, task modes, instances, exceptions, dashboard,
  registry) against the live backend, with a development user-switcher stub.

## 9. Troubleshooting

- **"I'm signed in but there's nothing here — no roles."** Your account was created (first
  sign-in provisions it) but hasn't been granted any roles yet, so you land on the calm
  "no access yet" screen. Ask your Amendia administrator to assign you a role (or stage it
  against your email before you sign in); sign in again once they have.
- **"Account disabled."** An administrator has disabled your account — every request is refused
  until it's re-enabled. Contact your administrator.
- **A control in Administration is greyed out.** Guardrails: you can't disable/last-admin-revoke
  yourself, and the platform always keeps at least one active admin. The tooltip says which.

## 10. Personas

This is the persona map for the operator UI. Role wording here matches the in-app role
descriptions (the Assign-role dialog / role rows). The **platform-administrator** persona
(Alex) has a dedicated companion how-to: [User Management Guide](../backend/docs/amendia_admin_user_management_guide.md).

| Persona | Role(s) | What they do | Notes |
|---|---|---|---|
| **Riya** (analyst) | `role.payments.ops_analyst` | Reviews assessments and drafts repairs and returns at analyst gates | Signs in as `riya`; SoD-excluded from approving repairs she drafted |
| **Marcus** (approver) | `role.payments.ops_approver` | Approves results and authorizes payment actions at approver gates | Signs in as `marcus` |
| **Priya** (process owner) | `role.process.owner`, `role.platform.admin` | Authors, validates, and activates process packs in the Registry; also administers users and roles | Signs in as `priya`; sees Registry **and** Administration |
| **Alex** (platform administrator) | `role.platform.admin` | Full administrative control: manages users, roles, and staged access | Signs in as `alex`; sees **only** Administration — proves the admin-only composition |

**Sam** is not a persona but a *state* demonstrator: a dev user seeded with **no** roles, so his
first sign-in lands in the roleless "no access yet" screen (§9) until an admin grants him access.

### Alex — Platform Administrator

**Mission.** Keep the right people able to do the right things: provision access (assign roles,
or stage them by email before someone first signs in), review who holds what, and disable
accounts that shouldn't have access — all without touching the payment-operations screens.

**Screens.** Administration → Users (users list + Pending-access tab), user detail
(roles / identities / account), and the assign-role and stage-access dialogs. Alex holds
`role.platform.admin` *only*, so his nav shows Administration and nothing else — no inbox,
instances, exceptions, or registry.

**Implemented actions.** Assign and revoke roles on a user; stage, edit, and remove pending
access by email (attaches on first sign-in); disable and enable accounts (disable takes a
consequence-acknowledging reason). Every action is recorded with his identity and a timestamp.

**Guardrails on his screens.** The UI disables and explains the actions that would break the
platform, and the server enforces them regardless: he can't disable his own account or revoke
his own admin role (`self_protection`), and the platform refuses to lose its last active
platform admin (`last_admin`).

**Friction that remains.** Identity re-linking/merging (`iss`/`sub`) is still API-only; there's
no SCIM/automated provisioning (staging by email is the bridge), no cross-cutting audit-report
browsing (each record shows its own who/when), and no bulk operations yet.

Auth friction from earlier iterations is resolved: sign-in is real OIDC (no placeholder),
decisions carry the acting user's durable Amendia id, and separation-of-duties keys off
those ids rather than dev-only synthetic names.

### Coverage matrix

Nav visibility per role (✓ = appears in that role's sidebar):

| Area | Analyst | Approver | Process owner | Platform admin |
|---|---|---|---|---|
| Task inbox & gates | ✓ (analyst gates) | ✓ (approver gates) | ✓ | — |
| Instances / exceptions / dashboard | ✓ | ✓ | ✓ | — |
| Registry (authoring) | — | — | ✓ | — |
| **Administration (users & roles)** | — | — | — | ✓ |

The operator surfaces (inbox / instances / exceptions / dashboard) appear for anyone with an
operator role, so a platform-admin-*only* user (alex) sees just Administration. Reads themselves
stay role-free server-side — those pages are still reachable by direct URL — this is nav-level
progressive disclosure, not enforcement. *A person with none of these roles sees the "no access
yet" state until an administrator grants one.*

### Genuinely future personas

Everything the four personas above need is implemented. What remains genuinely future is not a
new *screen* for an existing persona but new *capabilities*: an **automated SCIM-driven
joiner/mover/leaver lifecycle** (so provisioning isn't manual staging-by-email), and an
**access-review / audit-report** surface (the per-record who/when data exists; the cross-cutting
report doesn't). A read-only **auditor/compliance** persona would land with that reporting work.
