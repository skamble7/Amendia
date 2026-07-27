# Amendia — Onboarding Methodology: Audit, Gaps, and Proposed Doc Structure

**Purpose.** Amendia is a *generic process-execution platform*. Production success for any process depends less on
the platform code and more on whether the **onboarding methodology reliably grounds, designs, hardens, and
signs off** a process before it goes live. This doc audits that methodology as a system of **gates and
handoffs**, identifies where a real process could reach prod under-hardened, and proposes a doc structure that
makes the methodology legible.

Grounded in a full read of `amendia_process_discovery_playbook.md`, `amendia_process_onboarding_guide.md`, and
`amendia_mcp_implementor_guideline.md` (2026-07-27).

> **Status note (2026-07-27):** the gaps below (G1–G5) were subsequently written as methodology docs
> (`amendia_capability_hardening_certification_guide.md`, `amendia_go_live_readiness.md`,
> `amendia_design_signoff.md`, `amendia_operating_model.md`). The **final** doc structure keeps the existing
> descriptive filenames grouped into folders (rather than the numbered scheme sketched in §3 below); the reading
> order is carried by `amendia_operating_model.md`. This doc is retained as the audit/gap record.

## 1. The lifecycle, the four roles, and where each gate lives

| Stage | Role | Owning doc(s) | Output → gate |
|---|---|---|---|
| Discovery / as-is | Back-office + SMEs | `amendia_process_discovery_playbook.md` | Intake package (charter, narrative, BPMN, 8 inventories, classification, triage) → **SME/owner sign-off of the intake** ✅ (checklist exists) |
| Design / optimize + onboard | AI experts (Process Owner) | `amendia_process_onboarding_guide.md`, onboarding-UX docs, worked scenarios | Validated, activated pack → **7-stage validator** ✅ (strong) — but **no explicit business sign-off of the *optimized* design** ⚠️ |
| Capability build | MCP developers | `amendia_mcp_implementor_guideline.md`, `amendia_mcp_backed_onboarding_runbook.md` | Compliant MCP server → **contract self-check** ✅ — but **no behavioural hardening/certification gate** ⚠️ |
| Operate / govern | Operators, admins | `webui_user_guide.md`, `amendia_admin_user_management_guide.md`, `amendia_persona_map.md`, `amendia_auth_architecture.md` | Running process | — |

**Strengths worth stating plainly.** The design/contract/validation front is genuinely strong, and — critically —
many controls are **platform-enforced as validated configuration, not doc-dependent convention**: side-effectful
capability ⇒ HITL ≥ `approve_actions`; four-eyes/SoD enforced per-instance from who actually acted; a gateway may
only branch on a `required`, upstream-produced field; artifact writes validated against pinned schemas; packs
immutable + version-pinned at activation. That materially lowers the "a human forgot a control" risk class.

## 2. Gap analysis (prioritized — these are the production-readiness gaps)

**G1 · Capability hardening + certification (highest risk).** The MCP guideline is excellent on the *contract*
(self-describing schemas, acknowledgement shape, modeled-business-error signalling, versioning) and captures
`idempotent` as a descriptor field. It does **not** require, before a side-effectful capability is trusted with
real side effects in prod: (a) *proven* idempotency under blind retry (the double-payment risk), (b) endpoint
security (authn/authz on the MCP endpoint itself, not just downstream secret refs), (c) defined
timeout/retry/partial-failure behaviour against the real downstream, (d) a **capability acceptance test suite**
the server must pass. Today's "pre-onboarding self-check" is a contract checklist, not a behavioural
certification. This is where real-world risk concentrates.

**G2 · Go-live / process-acceptance gate (missing).** Onboarding ends at `active` — a *technical* activation, not
a business/risk decision to accept real traffic. There is no documented go-live gate: capabilities certified
(G1), HITL placement reviewed against a risk taxonomy, audit trail verified (G4), rollback/deprecate plan,
ops/on-call readiness, and a shadow/pilot period with a blast-radius cap. This is the control that would keep an
unhardened process out of prod.

**G3 · Optimized-design business sign-off (thin).** Discovery signs off the *as-is* intake. The AI experts then
produce an *optimized* agentic design (the whole point — it differs from as-is). There is no explicit gate where
the business + risk/compliance sign off that **optimized** design before build/activation. You named this
("workflow design and its sign-off"); today it's implied by the validator, which checks structure, not business
intent.

**G4 · Audit-trail integrity verification (near-term, not fully deferrable).** The platform records immutable
decisions and enforces SoD — good. But there is no step that *verifies* the trail captures what compliance needs
(who/what/when, artifact versions, each approval tied to the action it authorized) and is tamper-evident. We
found a live bug this month recording decisions a human never confirmed; for a system taking consequential
actions, audit integrity is a control, and it belongs in the go-live gate (G2), not a "future version."

**G5 · A methodology overview / operating-model spine (missing).** The individual docs are strong but there is no
single "here is the end-to-end path and its gates" overview a new customer/implementer reads first. The gates in
§1 live implicitly across docs rather than as one legible lifecycle.

**G6 · Doc organization.** ~88 docs mix three very different things: the ~8 **methodology** docs, the **ADRs**
(engineering decisions), and the **claude_code_prompts** (build-time dev artifacts). The methodology docs are
buried. Grouping them is what makes the methodology usable by a customer team.

## 3. Proposed doc structure (repo `backend/docs/`)

Group the *methodology* into one tree; keep ADRs and dev prompts separate.

```
backend/docs/
  methodology/
    00-operating-model.md            # NEW (G5) — the lifecycle, roles, gates, one picture
    01-discovery-playbook.md         # = process_discovery_playbook
    02-onboarding-guide.md           # = process_onboarding_guide (+ onboarding-UX refinements)
    03-capability-implementor-guide.md   # = mcp_implementor_guideline
    03a-capability-hardening-cert.md # NEW (G1) — behavioural certification for prod capabilities
    04-go-live-readiness.md          # NEW (G2/G4) — the production acceptance gate + audit verification
    05-design-signoff.md             # NEW (G3) — optimized-design business/risk sign-off gate
    reference/                       # platform_contracts_v1, contracts_reference, services_reference
    worked-examples/                 # wire-repair kits, worked scenarios, sample BPMN
  operations/                        # user guide, admin user mgmt, persona map, auth architecture, nemoclaw runbook
  adr/                               # unchanged — engineering decisions
  _build-prompts/                    # archive the claude_code_prompt_* dev artifacts (history, not methodology)
```

(Superseded by the final structure — see the status note above: descriptive filenames grouped into folders, no
numbered renames.) The physical move + cross-reference updates should be a reviewed CC change (git-tracked), done
**after** the structure is agreed.

## 4. Recommended sequence

1. **G1 — capability hardening/certification** (biggest prod risk; unblocks trustworthy side effects).
2. **G2 + G4 — go-live readiness gate incl. audit-trail verification** (the acceptance control; makes "are we
   prod-ready for process X" answerable).
3. **G3 — optimized-design sign-off gate.**
4. **G5 — operating-model overview** (ties it together; good to write once the new gates exist).
5. **G6 — the folder reorg** (mechanical; do it once the new docs exist so we move the final set once).

## 5. What this reframes about "production readiness"

Under the platform + methodology framing, the earlier domain concerns (real payment rails, sanctions, an LLM
proposing account changes) are **per-process** items the methodology must force to be grounded, hardened, and
signed off — they belong to G1/G3/G2, not to the platform. What remains genuinely **platform-level** and
independent of any process: the non-functionals (isolation, authn/authz, resilience, observability, audit
integrity). Of those, the deployment model (per-department instances on customer infra) materially reduces the
isolation/tenancy surface; audit integrity (G4) is the one that should not wait.
