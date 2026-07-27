# Amendia — Go-Live Readiness & Process Acceptance Gate

**Status:** the mandatory gate a process pack passes **after** technical activation and **before** it receives
real production traffic. Owned by the **Process Owner** with **risk/compliance** and **operations** sign-off.
**Audience:** process owners, risk/compliance, operations, platform admins.
**Companion documents:** `amendia_process_onboarding_guide.md` (technical activation), `amendia_capability_hardening_certification_guide.md`
(the capability certifications this gate consumes), `amendia_design_signoff.md` (the design this gate assumes was
approved), `amendia_process_discovery_playbook.md` (the charter metrics this gate measures against).

---

## 1. Why this exists — `active` is not "accepted for production"

Onboarding ends when a pack becomes `active`: it validated against the 7-stage validator, its ranges pinned, and
it is now eligible for triage. That is a **technical** state — it proves the pack is *well-formed and
executable*. It does **not** prove the process is *safe to run on real cases*: that its side-effectful
capabilities are certified, that its human gates sit where the risk is, that its audit trail actually
reconstructs, that there is a way to stop it, and that someone accountable has accepted the risk.

This gate is that acceptance decision. It is where **capability hardening, control placement, audit integrity,
recovery, rollback, and rollout** come together into one recorded, signed-off **Go-Live Package**. A pack may be
`active` in a deployment and still be **held** from real traffic (scoped away by triage) until it passes this
gate. Nothing here is enforced by platform code — it is the methodology's final control, and it is deliberately a
human decision.

---

## 2. Preconditions (all true before the review convenes)

- **Design signed off.** The optimized agentic design — not just the as-is intake — has business + risk sign-off
  (`amendia_design_signoff.md`). This gate accepts an *implementation of an approved design*, not the design.
- **Pack validated & active.** The 7-stage validator is clean; the pack is `active` with its resolution sidecar
  (pins + `required_execution_profile`).
- **Every side-effectful capability certified.** Each `side_effectful` capability the pack binds has a **current,
  passing Capability Certification Record for the pinned version** (idempotency C2, failure-recovery C3,
  endpoint-security C4 at minimum). **No certification → the gate cannot pass.**

---

## 3. The readiness review — dimensions & checklist

### 3.1 Capabilities
- [ ] Every `side_effectful` binding maps to a capability with a passing certification for the **pinned** version.
- [ ] Every `read_only` capability is contract-clean (MCP guideline §7).
- [ ] Every capability endpoint is reachable **from the production deployment** (not a dev/staging URL) over the
      declared transport, secured (auth, TLS), with secrets resolved from references — verified in the prod env.

### 3.2 Control placement (a risk review, not just "it validated")
- [ ] Every side-effectful step is gated `≥ approve_actions` (platform-enforced — confirm nothing was reclassified
      `read_only` to dodge a gate).
- [ ] Four-eyes / SoD covers every pair where the preparer must not be the approver.
- [ ] Oversight level per step is **appropriate to that step's risk**, not merely valid — a high-value or
      irreversible step warrants stricter review than the minimum the validator accepts.
- [ ] Timers/escalations exist for every SLA, and escalate to a real role.

### 3.3 Triage scoping & blast radius
- [ ] Triage rules catch **only** the intended cases; no priority collision with another active pack (lowest
      priority wins — confirm this pack wins/only where intended).
- [ ] Initial rollout is blast-radius-capped: an amount ceiling, a reason-code/whitelist scope, or a volume cap,
      widened only by the rollout plan (§3.8).

### 3.4 Audit-trail verification (do not defer)
The platform records immutable decisions and enforces SoD from who actually acted. This step **verifies** that
record is complete and trustworthy before real actions ride on it:
- [ ] **Reconstruct a full case end-to-end from the trail alone** — every step's inputs/outputs (with artifact
      versions), every human decision (who, when, decision, comment), and **each side-effect approval tied to the
      `action_id` of the effect it authorized**.
- [ ] The record captures decisions **only** on explicit human confirmation (no auto-recorded decisions) — re-verify
      this after **any** change to the HITL/decision path (a defect here has shipped before).
- [ ] Immutability/tamper-evidence holds; retention meets the applicable compliance requirement.

### 3.5 Failure & recovery readiness
- [ ] Behaviour is defined and **fail-safe** when an MCP server / LLM / infra dependency is down — a side effect
      never fires on a degraded/ambiguous path; a technical failure fails or retries, it does not guess.
- [ ] Idempotent retry is proven at the capability level (cert C2/C3) so a runtime retry cannot double an effect.
- [ ] No orphaned in-flight instances on restart; there is a recovery runbook for a stuck/failed instance.

### 3.6 Rollback / deprecate plan
- [ ] A documented way to **stop** the process: `deprecate` the pack (finishes in-flight instances, accepts no new
      ones) and where new cases route instead.
- [ ] Named owner who can trigger rollback and the criteria that would.

### 3.7 Operations readiness
- [ ] Monitoring/alerting for stuck instances, failed dispatches, SLA breaches, and repeated capability errors.
- [ ] On-call ownership named; an incident runbook for the common failures (dovetails with the operator runbooks).

### 3.8 Rollout plan
- [ ] A shadow or pilot period with the blast-radius cap from §3.3, explicit success criteria to widen, and the
      **charter metrics** (from discovery) instrumented so before/after is measurable.

### 3.9 Sign-offs
- [ ] **Process Owner**, **risk/compliance**, and **operations** have each signed off, recorded against the pack
      version.

---

## 4. The Go-Live Package (the record)

Assemble and retain, per `pack_key@version`: the pinned pack + resolution sidecar; the **Capability Certification
Records** for every side-effectful capability; the completed §3 review with findings and remediations; the
rollout plan + blast-radius scope; and the three sign-offs. This package is the auditable artifact that says
"this process was accepted for production, by these people, under these conditions." It is what an auditor (or a
post-incident review) reads to see the process was not run on trust.

---

## 5. After go-live

- Watch the **charter metrics**; make the widen-blast-radius decision against the §3.8 success criteria.
- **Re-run this gate** on any material change: a new pack version, a **new capability version** (re-certify then
  re-accept — certification and acceptance are per pinned version), a change to control placement, or a change to
  triage scope. A live pack is immutable; a change is a new version that re-enters onboarding → this gate.
- Feed anything learned back into the discovery/design docs so the next process onboards better.

---

## 6. Non-goals & relationship to the platform

- This gate does not replace the platform's enforced controls (approval gates, SoD, pinning, profile guard); it
  confirms they are placed correctly and that the things behind them are trustworthy, and it adds the
  human/organisational acceptance the platform cannot make on your behalf.
- It does not re-do design (that is `amendia_design_signoff.md`) or capability certification (that is the hardening
  guide) — it **consumes** both and adds process-level acceptance.
- Passing it is a decision by accountable people, recorded — not a green test. That is the point: a system that
  takes real-world actions goes live because someone accountable accepted it, with the evidence in hand.
