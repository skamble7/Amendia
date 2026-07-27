# Amendia — Optimized-Design Review & Sign-Off Gate

**Status:** the mandatory gate between the AI experts' **optimized agentic design** and the work that follows it
(capability build + onboarding + go-live). Owned by the **Process Owner** with **business SMEs** and
**risk/compliance** sign-off.
**Audience:** AI/process designers, business SMEs and process owner, risk/compliance.
**Companion documents:** `amendia_process_discovery_playbook.md` (the signed-off *as-is* intake this design
transforms), `amendia_process_onboarding_guide.md` (how the signed design becomes a validated pack),
`amendia_capability_hardening_certification_guide.md` (the build bar the agreed capability inventory feeds),
`amendia_go_live_readiness.md` (the later acceptance of the built implementation).

---

## 1. Why this exists — three different acceptances, and this is the missing middle one

There are **three** distinct acceptance points in a process's life, and they answer different questions:

1. **Discovery sign-off** (playbook Phase 6): *"Is this an accurate picture of how we work today?"* — the business
   owns the truth of the **as-is**.
2. **Design sign-off** (this gate): *"Is this optimized agentic design what we want built, and is it safe?"* — the
   business + risk accept the **to-be**.
3. **Go-live acceptance** (`amendia_go_live_readiness.md`): *"Is the built, onboarded process accepted for real
   traffic?"* — accountable acceptance of the **implementation**.

The middle one is easy to skip because the platform's 7-stage validator gives a reassuring green. But the
validator checks **structure**, not **intent**: a design can be perfectly well-formed — bindings complete,
side-effects gated, gateways reading required fields — and still automate the wrong step, remove a control the
business quietly relied on, place a human gate where it adds no safety, encode a business rule wrong, or hand an
agent a consequential judgment nobody agreed it should make. None of that is a validator finding; all of it is a
**design** decision.

And the whole point of the AI-expert stage is **optimization** — which means the to-be **deliberately differs**
from the as-is. Unreviewed change is exactly where value is lost (automating the easy 20% and missing the point)
or where safety is lost (optimizing away a control). This gate accepts the *change*, **before** money is spent
building capabilities and long before real cases run. It is cheap to move a box on a diagram here; it is
expensive after the MCP servers are built and the pack is live.

---

## 2. What the AI experts bring to the gate (the design package)

- **The optimized design** — the executable BPMN (the to-be) + the manifest-level decisions: which steps became
  agent capabilities, which stayed human and why, the decisions made explicit (gateways / decision tables), the
  control model (HITL level per step, four-eyes/SoD pairs, side-effect gating), timers/escalations, and the
  exception/undo handling.
- **The delta from as-is** — the heart of the review: a plain "what changed and why," mapped to the charter's
  expected benefits. Steps automated; steps removed or merged; human touchpoints removed, added, or relocated;
  handoffs changed; new or removed controls. Every change traceable to an intent.
- **The capability inventory to build** — each capability the design needs, with its **`side_effect`
  classification** (read-only vs side-effectful) and the system it touches — so build scope *and* the
  certification bar (G1) are agreed here.
- **The triage scope** — which incoming cases this process will claim.

---

## 3. The review — dimensions & checklist (this is a *business/risk* review, not a structural one)

### 3.1 Fidelity to intent
- [ ] The design achieves the charter's **trigger → outcome** and its **expected benefits**; the charter metrics
      remain measurable on the to-be.

### 3.2 Delta acceptance (the core)
- [ ] Every change from as-is is understood and accepted — **especially removed steps and removed/relocated human
      touchpoints.** For each: was that step a control someone relied on? If a human check was automated or
      dropped, is the risk consciously accepted or re-covered elsewhere?

### 3.3 Control-model review (at design time — cheapest to fix)
- [ ] Every side-effectful step is behind `≥ approve_actions`; four-eyes/SoD sits on the pairs where preparer and
      approver must differ.
- [ ] The oversight level per step matches that step's **risk**, not merely the validator's minimum — a
      high-value/irreversible step warrants stricter review.
- [ ] The **automation-vs-human boundary** puts accountability where the organisation wants it to rest.

### 3.4 Decision correctness
- [ ] Each gateway / decision table encodes the **real** business rule, reviewed and owned by the SME who owns
      that rule; edge cases and thresholds are right; the field each decision reads is one an earlier step always
      produces.

### 3.5 Exception & undo completeness
- [ ] Every anticipated non-happy outcome (rejected, hit, insufficient info, …) has a branch the business agrees
      with; every irreversible action has an accepted **undo** — or a conscious "no undo, so extra approval."

### 3.6 Agent-judgment scope (decide it here, explicitly)
- [ ] Wherever the design has an **agent make or propose a consequential judgment** (e.g. an agent proposes a
      correction to an account number, or drafts an instruction that moves money once approved), the business +
      risk **explicitly accept that scope** and the human gate that bounds it. "Should an agent be allowed to
      propose *X*?" is answered here, deliberately — not left implicit in a service task. Also confirm the agent's
      inputs (which may include untrusted content) and its tool scope are acceptable for that judgment.

### 3.7 Roles & accountability
- [ ] The swimlane → role mapping is agreed, and the organisation accepts who is accountable at each human gate.

### 3.8 Capability scope agreed
- [ ] The capability inventory (with side-effect classification and target systems) is agreed with the MCP-dev
      team and the system owners — this **is** the build scope and sets which capabilities must clear the
      hardening/certification bar (G1) before go-live.

### 3.9 Triage scope
- [ ] The process claims only the intended cases; no unintended overlap with another process.

---

## 4. Sign-off & record

- **Who signs.** The **Process Owner**, **risk/compliance**, and the **SME owner(s)** of the business rules the
  design encodes. The design is not a purely technical artifact — the people accountable for the *business
  outcome* accept it.
- **The record.** A **Design Sign-Off Record** for the process (and version): the approved to-be design, the
  accepted delta-from-as-is, the agreed capability inventory + classifications, and the sign-offs. It becomes an
  input to onboarding and to the go-live package.
- **What it authorizes.** Capability development (against G1) and onboarding proceed **against a signed design**.
  A **material** design change after sign-off — a new/removed step, a changed control, a changed decision rule, a
  widened agent judgment, a new side-effectful capability — **re-enters this gate** before build/onboarding
  continues. Cosmetic changes do not.

---

## 5. Non-goals & relationship to the other gates

- This gate accepts the **design**, not the **truth of the as-is** (that was discovery) and not the **built
  implementation** (that is go-live). Three questions, three acceptances.
- It does **not** verify capability behaviour/hardening (that is certification, G1) or runtime/audit readiness
  (that is go-live, G2/G4). It verifies the *design is the right, safe thing to build*.
- Its value is **timing**: it catches wrong or unsafe design while it is still a diagram, before build spend and
  before any real case runs. Skipping it doesn't remove the review — it just moves it to production, at the worst
  possible cost.
