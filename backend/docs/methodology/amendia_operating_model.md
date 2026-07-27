# Amendia — Operating Model & Methodology Overview

**Read this first.** It is the one-page map of how a process goes from "how we work today" to "running safely in
production on Amendia" — the stages, the four roles, the gates, and where each detailed doc lives. Everything
else is depth behind this map.

---

## 1. What Amendia is

Amendia is a **generic, domain-neutral process-execution platform**. You give it a **BPMN process** (as data)
and a set of **external capabilities** (MCP tools that connect to your systems); it **executes the process
faithfully**, step by step, pausing at the human approval gates you defined, validating every artifact against a
pinned schema, and recording an immutable audit trail. It is not a payments product — the wire-transfer process
is a *reference example*. The same platform runs any process you can describe as a diagram + capabilities.

Two things follow, and they define this whole document:

- **The platform is generic and enforces a set of controls by construction** (see §5). It does not "know" your
  domain.
- **Making a *specific* process safe and valuable in production is the job of the methodology** — grounding the
  requirements, designing the optimized workflow, hardening the capabilities, and signing each off. The platform
  is the engine and the guardrails; the methodology is the per-process due diligence.

Production readiness is therefore two things at once: **platform soundness** (the engine + guardrails) **and
methodology discipline** (each process taken properly through the path below).

---

## 2. The lifecycle in one picture

| # | Stage | Who (role) | Produces | Gate at the end | Detailed doc(s) |
|---|---|---|---|---|---|
| 1 | **Discovery** — document the as-is, decide what to automate | Back-office / SMEs + process owner | Intake package: charter, narrative, BPMN, 8 inventories, classification, triage | **Discovery sign-off** — *"is this an accurate picture of how we work today?"* | `amendia_process_discovery_playbook.md` |
| 2 | **Design** — optimize into an agentic workflow | AI/process experts | The optimized to-be BPMN + control model + capability inventory + delta-from-as-is | **Design sign-off** — *"is this what we want built, and is it safe?"* | `amendia_design_signoff.md` |
| 3 | **Build capabilities** — implement the MCP tools | MCP developers | Contract-compliant, **certified** capabilities | **Capability certification** — *"is each capability safe to trust with a real action?"* | `amendia_mcp_implementor_guideline.md`, `amendia_capability_hardening_certification_guide.md` |
| 4 | **Onboard** — turn the diagram into a validated pack | Process owner (wizard) | A validated, version-pinned, `active` ProcessPack | (7-stage validator — structural) | `amendia_process_onboarding_guide.md` (+ runbook, worked scenario) |
| 5 | **Accept for production** — decide it can take real cases | Process owner + risk/compliance + ops | A recorded Go-Live Package + rollout plan | **Go-live acceptance** — *"is the built process accepted for real traffic?"* | `amendia_go_live_readiness.md` |
| 6 | **Operate & govern** — run, monitor, manage users | Operators, admins | A running, audited process | (ongoing) | `Amendia_User_Guide.md`, `amendia_admin_user_management_guide.md`, `amendia_persona_map.md`, `amendia_auth_architecture.md`, `amendia_nemoclaw_operator_runbook.md` |

Good work upstream makes downstream a confirmation, not a rebuild: faithful discovery makes design fast; an
agreed design makes the capability scope and onboarding clear; certified capabilities make go-live a decision,
not a leap.

---

## 3. The four roles

- **Back-office team / SMEs** — own the *truth* of how the process works today; produce the as-is BPMN + intake.
- **AI / process experts** — design the *optimized* agentic workflow: what becomes an agent capability, what
  stays human, where the control gates sit.
- **MCP developers** — build the capabilities (connectors to real systems) to the contract *and* the hardening
  bar, and certify the side-effectful ones.
- **Operators & admins** — run the live process, act on the human gates, manage users/roles, monitor and govern.

---

## 4. The gates (the control spine)

Four human checkpoints, each answering a different question, plus the platform's own enforced controls (§5):

1. **Discovery sign-off** — the as-is is accurate (business owns the truth).
2. **Design sign-off** — the optimized to-be is the right, safe thing to build; the delta from as-is is accepted;
   any agent judgment scope is explicitly agreed. *Reviews intent — the validator only checks structure.*
3. **Capability certification** — every side-effectful capability is proven idempotent, failure-safe, secured,
   and second-party signed, **before** it can be bound into a go-live pack.
4. **Go-live acceptance** — the built, onboarded process is accepted for real traffic by accountable people, with
   capability certifications, control-placement review, **audit-trail verification**, rollback plan, and a
   blast-radius-capped rollout — all recorded.

The three sign-offs (1, 2, 4) are three *distinct* acceptances — of the as-is, the design, and the
implementation. Skipping any doesn't remove the review; it moves it to production, at the worst cost.

---

## 5. What the platform enforces vs what the methodology enforces

**The platform enforces by construction (validated configuration, not convention):** a side-effectful capability
cannot run without a human authorization gate (`≥ approve_actions`); the preparer cannot approve their own work
(four-eyes / separation of duties, per-instance); a gateway may only branch on a `required`, upstream-produced
field; every artifact write is validated against its pinned schema; packs are immutable and version-pinned at
activation; the runtime refuses a pack whose profile it can't run. These remove the "someone forgot a control"
risk class.

**The methodology enforces what the platform cannot know or check:** that the *right* steps were automated and the
*right* controls kept (design sign-off); that the capability *behind* a gate does exactly, only, and reliably what
it claims (certification); that the audit trail actually reconstructs and someone accountable accepted the risk
(go-live). Safety comes from **both** — the platform's guardrails and the methodology's due diligence.

---

## 6. Deployment shape & scope

Amendia is deployed **on the customer's infrastructure**, typically **one instance per department** — which makes
it effectively single-tenant per deployment and keeps each department's capability blast-radius contained. The
residual concerns are operational (a fleet of instances to patch, monitor, and back up) rather than tenancy
isolation. Non-functional depth (resilience, observability) can grow across versions; **audit-trail integrity**
(part of go-live acceptance) is the one control that should not wait.

---

## 7. Document index

**Methodology (the path above):** discovery playbook → design sign-off → MCP implementor guideline + capability
hardening/certification → onboarding guide (+ mcp-backed runbook, worked scenario) → go-live readiness.

**Operate & govern:** user guide, admin user-management guide, persona map, auth architecture, nemoclaw operator
runbook.

**Reference (the contracts underneath):** `amendia_platform_contracts_v1.md`, `amendia_contracts_reference.md`,
`amendia_services_reference.md`, `amendia_agent_runtime_execution_pipeline.md`.

**Decisions & history:** the ADRs under `adr/`; the methodology audit
(`amendia_methodology_audit_and_doc_structure.md`) records the gap analysis and the doc-structure plan this
overview anchors.

---

*This overview is the front door. When the lifecycle, a role, or a gate changes, update this map first, then the
detailed doc behind it.*
