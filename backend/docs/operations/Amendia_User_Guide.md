# Amendia — User Guide

The operator UI for the Amendia agentic payment-exception platform: a task inbox with
the four HITL decision modes, instance and exception views, a dashboard, and the process
registry. Everything on screen comes from the live backend.

> **Personas** — who the dev users are, their jobs, journeys, and guardrails — live in the
> [Persona Map](amendia_persona_map.md). This guide is operational: how to use the app.

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
- **In local dev**, it goes to the bundled Keycloak. Sign in as one of the five dev users:

  | Username | Role(s) |
  |---|---|
  | `riya` | Payments Ops Analyst |
  | `marcus` | Payments Ops Approver |
  | `priya` | Process Owner + Platform Admin |
  | `alex` | Platform Admin (only) |
  | `sam` | *(none — first sign-in lands in the "no access yet" state)* |

  Password for all five: `dev-password` (**dev only** — see the Keycloak README). For who these
  users are and what each role does, see the [Persona Map](amendia_persona_map.md).

Your name and roles in the top bar come from Amendia's own identity service (`GET /me`),
not from the login token — Amendia decides what you can do, your IdP only proves who you are.

The top-bar user menu also holds a **theme** control — Light / Dark / System. Your choice is
remembered on this device; **System** follows your operating system's appearance live.

### Switching users (dev)

There is **no user switcher** — that was the old development placeholder. To act under a
different role (e.g. an analyst drafts a repair, then an approver authorizes it, which
separation-of-duties requires be different people), **sign out and sign in as the other
user**. This is the same flow a real operator uses, so what you see in dev is honest.

### Do the work

1. Open the app and sign in (as **riya** for the analyst gates).
2. Go to **Exceptions → Generate exception (via stub source)** and pick a reason code
   (`AC01`). This calls the real stub, which publishes a real event; an instance starts.
3. Its gates appear in the **Task inbox**. Open one, **Claim** it, and record a decision.
4. When a gate needs the approver role, sign out and sign in as **marcus**.

Registry (process authoring) is only visible with the **process-owner** role.

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
any stage reports an error. On the **Policies** step you can give each pack-local role a
human-friendly label and description — admins see these when granting the role (ADR-026).
Visible only to users with the process-owner role.

## 6. Administration — Users (platform admins)

**Administration → Users** is visible only to users with `role.platform.admin` (same
progressive-disclosure mechanism as Registry). It is where the platform administrator manages
who exists and what they can do. For the full admin playbook (onboarding, offboarding, guardrails,
API-only edges) see the [User Management Guide](amendia_admin_user_management_guide.md); the
platform-administrator persona is profiled in the [Persona Map](amendia_persona_map.md). Two tabs:

- **Users** — every provisioned user with their status, roles (platform admin stands apart),
  the identity provider they came from, and when they were first seen. Search by name / email /
  id and filter by status, by role, or by **no roles** (handy for spotting people who signed in
  but haven't been granted access yet). Disabled users are shown muted. Open a user for detail.
- **Pending access** — roles **staged by email before someone first signs in**. Each entry
  shows the email, the staged roles, who staged them and when, and the note that they *activate
  on first sign-in* — at which point the roles attach to the new account and the entry drops off
  this tab (it only ever lists people who haven't signed in yet). Stage new access, edit the
  staged roles, or remove an entry.

**User detail** has three blocks:

- **Roles** — each assigned role with a plain-language description and who assigned it/when;
  **Assign role** opens a **master-detail picker** — packs (plus a *Platform* group) on the left,
  that group's roles on the right — so the list stays short as more packs are onboarded. The roles
  come from what active packs actually use (`GET /roles`, ADR-026), platform admin is flagged as
  elevated, roles already held show as *granted*, and a **custom-role** field grants a role a
  not-yet-active pack references. Revoke from any row; a user with no roles shows an inline
  "assign a role" prompt.
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

## 7a. BPMN conformance — what executes (the two profiles)

Amendia ingests **Full BPMN** (upload any diagram) and executes the **Common Executable** conformance
level. Onboarding **classifies** each element rather than rejecting the diagram, and a coverage report
shows what will run vs what is documentation-only.

- **`common_executable` (the default runtime level).** Parallel gateways (fork/join), **timers**
  (intermediate-catch delays and **SLA timer boundary events** that escalate a HITL gate when a human
  is late), **error boundary events** (a modeled business rejection routes to a rework/return path
  instead of failing), **inbound messages** (a message-catch / receive task parked and resumed by a
  correlated business message; an **event-based gateway** waits for the first of a message vs a timer),
  **embedded sub-processes**, and the **full BPMN task set** (`serviceTask`, `userTask`, `sendTask`,
  `receiveTask`, `scriptTask`, `manualTask`, `businessRuleTask` — each routed to a capability, a human,
  or a message) all execute.
- **`common_subset` (a deliberately conservative envelope).** A deployment may run only the Phase-0/1
  base subset (`start`/`end`, `serviceTask`/`userTask`, `exclusiveGateway`, conditional flow). Such a
  runtime **refuses** a pack that needs beyond-subset constructs, with a clear `pack_requires_profile`
  reason.
- **Documentation-only elements** (lanes/personas, external-system pools, message flows, an inline
  DMN decision table, a `callActivity`, an inline `<script>` body) are **kept and shown as
  `documented`** in the coverage report — they enrich onboarding inference but are not executed.
  Business-rule tasks execute via a **bound decision capability** (native DMN evaluation is a separate
  feature track); inline scripts and `callActivity` are refused for execution.

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
