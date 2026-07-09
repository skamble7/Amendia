# Amendia — Persona Map

**Version:** 1.1 (reflects webui v0.3 — Administration release, ADR-014, and the auth releases ADR-012/013)
**Canonical location note:** this file is the full persona map. The [Web UI User Guide](../../webui/webui_user_guide.md#10-personas) §10 should carry only the quick persona table and a pointer here — deep profiles are maintained in this file only, to prevent drift. The platform-administrator how-to is the [User Management Guide](amendia_admin_user_management_guide.md).

The map covers four human personas (all real, seeded dev users), one state demonstrator, and one non-human actor. Roles here are enforced, not decorative: navigation is role-composed, task claiming checks roles server-side, separation-of-duties exclusions are computed per process instance, and every decision and administrative action is recorded immutably against the acting user's durable Amendia id. Role wording below matches the in-app role descriptions (the Assign-role dialog).

---

## Riya — Operations Analyst

**Role:** `role.payments.ops_analyst` · **Dev sign-in:** `riya` · **Mission:** work the queue; get exceptions moving with sound judgment.

**Jobs to be done.** Review what agents concluded before it counts; correct agent output when it's close-but-wrong (edit & approve); perform genuinely-human steps — like drafting and sending a request for information — with the agent's pre-draft as a starting point.

**Screens.** Task Inbox and Task Detail are home; Exceptions detail for context; Instances to see where a case stands; Dashboard for the overview.

**Implemented actions.** Claim/decide *Review* gates (approve / edit & approve — schema-validated live / reject with comment); complete *Manual* gates via schema-generated forms; generate dev exceptions via the stub button.

**Guardrails on her.** SoD-locked from approving work she influenced — rendered before she clicks, with the reason, and enforced server-side against her `usr-…` id. Her edits are re-validated against the pinned artifact schema.

**Current friction.** Gate density on routine repairs (a pack-versioning tuning exercise); polling latency before new tasks appear; SLA due-dates display but nothing fires.

## Marcus — Operations Approver

**Role:** `role.payments.ops_approver` · **Dev sign-in:** `marcus` · **Mission:** four-eyes control; nothing consequential happens without an accountable human.

**Jobs to be done.** Approve or reject agent results as-is (sanctions screenings — deliberately no editing); approve drafted repairs; **authorize side-effectful actions** — the money-moving signature — with full sight of exactly what will execute and a mandatory recorded rationale.

**Screens.** Task Inbox (approver gates), Task Detail (*Approve result* and *Authorize actions* variants), Instances for after-the-fact audit.

**Implemented actions.** Claim/decide approve-result gates; authorize actions with per-action checkboxes (unchecked actions never execute) and mandatory comment; reject with the pack-defined rejection semantics.

**Guardrails on him.** The same SoD machinery; closed decision sets per mode (a sanctions result cannot be edited, only accepted or rejected); identity and comment immutable on the record.

**Current friction.** Comments are the only structured rationale (no rejection reason codes); no escalation targets behind *Escalate*.

## Priya — Process Owner (+ Platform Admin in dev)

**Roles:** `role.process.owner` + `role.platform.admin` · **Dev sign-in:** `priya` · **Mission:** make new exception-handling processes executable — safely.

**Jobs to be done.** Understand the building blocks (capabilities with side-effect classifications, artifact schemas); onboard packs: manifest → BPMN → validation → activation; read validation reports and fix precisely what they name; understand version pinning.

**Screens.** Registry (Processes catalog + onboarding wizard, Capabilities, Schemas), Dashboard — and, via her admin role, the full Administration area (she demonstrates that personas are role compositions, not fixed people).

**Implemented actions.** Full wizard flow (submit, upload BPMN, validate with the 7-stage report, activate with range→pin review); catalog browsing; everything in Alex's profile below, via her second role.

**Guardrails on her.** The onboarding validator: she cannot activate a pack referencing unregistered capabilities, violating a HITL floor, or leaving a side-effectful capability without an authorization gate. Versions are immutable — fixes are new versions.

**Current friction.** Capability and schema *registration* is API-only (browsing is in the UI); manifest authoring is raw JSON — no guided binding editor.

## Alex — Platform Administrator

**Role:** `role.platform.admin` (only) · **Dev sign-in:** `alex` · **Mission:** keep the right people able to do the right things — provision, review, and revoke access, accountably, without touching payment operations.

**Jobs to be done.** Grant access to people who signed in roleless; stage access by email before someone's first day; change what someone can do as their job changes; offboard leavers (disable, paired with the IdP-side disable); answer "who gave this person approval rights, and when?"

**Screens.** Administration → Users (Users + Pending-access tabs), user detail (Roles / Identities / Account blocks), assign-role and stage-access dialogs. Alex holds the admin role *only*, so his nav shows Administration and nothing else — the admin-only composition, proven.

**Implemented actions.** Assign/revoke roles; stage, edit, and remove pending access by email (attaches automatically on first sign-in); disable (with required reason) and enable accounts. Every action recorded with his identity and timestamp (`assigned by · at`, `staged by · at`).

**Guardrails on him.** Server-enforced and rendered as disabled controls with explanations: he cannot disable his own account or revoke his own admin role (`self_protection`), and the platform refuses to lose its last active admin (`last_admin`).

**Current friction.** Identity re-linking/merging is API-only; no SCIM/automated lifecycle (staging-by-email is the bridge); no cross-cutting audit-report browsing (per-record who/when exists); no bulk operations.

---

## Sam — a state, not a persona

Dev user `sam` is seeded with **no roles**: his first sign-in JIT-provisions an account that lands on the calm "no access yet" full-page state — demonstrating that authentication grants entry, never capability, and exercising the roleless composition until an admin grants him a role.

## The Agent — non-human actor

Capabilities executing under the runtime: they enrich, assess, draft, screen, and *propose*. The architecture is legible in what the agent **cannot** do: decide a HITL task, execute a side-effectful action without human authorization, write an artifact that fails its schema, or act outside the pinned process version. Its work is first-class and attributed (purple actor-log entries, "Drafted by agent" markers) so humans always know which colleague did what.

---

## Coverage matrix — nav visibility per role

| Area | Analyst | Approver | Process owner | Platform admin |
|---|---|---|---|---|
| Task inbox & gates | ✓ (analyst gates) | ✓ (approver gates) | ✓ | — |
| Instances / exceptions / dashboard | ✓ | ✓ | ✓ | — |
| Registry (authoring) | — | — | ✓ | — |
| **Administration (users & roles)** | — | — | — | ✓ |

Operator surfaces appear for anyone holding an operator role, so a platform-admin-*only* user (alex) sees just Administration. Reads stay role-free server-side (pages remain reachable by direct URL) — the matrix is nav-level progressive disclosure; mutations are what the server role-guards. A person holding none of these roles sees the "no access yet" state until an administrator grants one.

## Genuinely future personas

What remains future is not a new screen for an existing persona but new *capabilities*: an automated **SCIM-driven joiner/mover/leaver lifecycle** (replacing manual staging-by-email), and an **access-review / audit-report** surface (the per-record who/when data exists; the cross-cutting report doesn't). A read-only **auditor / compliance** persona lands with that reporting work — their data model (immutable decisions, actor logs, checkpoints, pins) is already fully built; only their screens are missing.

---

*Maintainers: this file is the canonical persona map — update it in the same PR as any role, screen, or guardrail change; keep user guide §10 as a summary + pointer. When a friction item is resolved, strike it here and note it in the user guide changelog.*
