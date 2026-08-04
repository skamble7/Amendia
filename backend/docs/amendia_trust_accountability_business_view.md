# Amendia — Trust, Control & Accountability: What We Have and Where We're Going

_A business-stakeholder view of how Amendia stays governable, traceable, explainable, and auditable. Companion to the engineering assessment.

## Why this matters

Amendia lets AI agents carry out real business processes — approving a wire repair, screening a party, resolving an exception. The moment software makes or assists decisions that have money, customers, or compliance attached, four questions decide whether an organization can actually trust it:

1. **Can we control what the AI is allowed to do?** (Governance)
2. **Can we trace where every piece of information came from?** (Lineage)
3. **Can we explain why it did what it did?** (Explainability)
4. **Can we prove all of the above to an auditor later?** (Audit)

These are not features you sprinkle on at the end. They are foundational — a platform either builds them into how work flows, or it spends years retrofitting them under regulatory pressure. The good news is that Amendia built most of this into its core from the start. This document explains, in plain terms, what is genuinely in place today and where the honest gaps are, so we can plan the work to close them.

## The short version

Amendia's foundations here are strong because these properties fall out of *how the platform runs work*, not from an add-on module. Every step records who acted, every piece of data is tied to a fixed, versioned definition, and sensitive actions require a real second person to approve — enforced by the system, not by policy on paper.

Where we are still maturing is on **showing and proving**: the raw record of everything that happened exists, but we don't yet present it as a clean, human-readable trail, and we don't yet keep it in a dedicated, tamper-resistant vault built for auditors. In short: **the memory is there; the reporting and the strongroom are the next build.**

## 1. Governance — controlling what the AI (and people) may do

**What we have.** Amendia enforces real controls at the moment work happens, not as guidance. Sensitive steps require a **four-eyes approval**: the person who prepares an action cannot be the same person who approves it — the system blocks that overlap automatically, every time. Who is allowed to approve what is tied to defined roles, and the platform protects its own control structure (for example, it won't let the last administrator be removed, which would leave the system ungoverned). Just as importantly, when an AI capability runs, the list of external systems it is permitted to contact is derived automatically from what that capability formally declares it needs — there is no hidden, hand-maintained list of "who can talk to whom."

**The gap.** That automatic "permitted destinations" control is fully enforced only in our most secure, sandboxed running mode. In the lighter-weight mode we use for development and simpler deployments, the permitted list is still calculated but not actively enforced. We also don't yet keep a formal, authored rulebook that a compliance officer could inspect and version independently — governance today is expressed through roles and declared contracts rather than a standalone, reviewable policy document.

**Why it matters.** Four-eyes and role separation are exactly the controls auditors and regulated customers ask about first, and we can demonstrate them. Closing the enforcement gap and adding an inspectable rulebook is what turns "we have strong controls" into "we can hand you the controls to review."

## 2. Lineage — tracing where every piece of information came from

**What we have.** Every piece of data the platform produces is tied to a fixed, versioned definition of what that data is — so a record from six months ago still points to the exact template that created it, even if we've since changed how the process works. The platform also records, for every step, precisely which earlier outputs fed into it. Human-created information is marked as such, and undoable actions keep a snapshot so they can be reversed cleanly. In other words, the complete chain — from raw input to final outcome — is captured.

**The gap.** That chain is *recorded* but not yet *presented*. If someone asked "walk me through how this final decision was built, input by input," we could reconstruct it, but we don't yet have a screen or report that draws that picture for them.

**Why it matters.** Traceability that lives only in the plumbing satisfies engineers; traceability a customer or regulator can *see* satisfies a compliance review. The underlying record already exists, so this is about surfacing it, not rebuilding it.

## 3. Explainability — explaining why it did what it did

**What we have.** For every sensitive step, Amendia captures the single most important thing about human–AI collaboration: **what the AI proposed versus what the human actually approved.** If the agent suggested one action and the reviewer changed it before approving, that difference is on the record, along with who approved it and any comment they left. Every step logs which actor — AI capability or named person — did what, and when. In our secure mode, each AI action is also linked to a detailed technical trace.

**The gap.** The record shows *that* an AI capability acted and *when*, but not the agent's own *reasoning* for its choice — the "why the AI thought this was right" is not yet captured. And what we do have is currently available only through a technical/diagnostic view, not a clean, plain-language decision trail a business user would read.

**Why it matters.** "The AI proposed X, a named human changed it to Y and approved it" is already a powerful, defensible story — most platforms can't say that. Adding the agent's rationale and a readable trail turns a strong technical foundation into something we can confidently put in front of a customer or an examiner.

## 4. Audit — proving it later

**What we have.** The platform keeps a durable, replayable record of each process run: the full sequence of steps, who acted, and the data at each point is persisted as work progresses. Nothing quietly disappears mid-run.

**The gap.** This is our least-mature pillar and the highest priority. Today that durable record is a byproduct of how the engine runs — it's kept in a form designed for the software to resume work, not for an auditor to query. The live stream of business events (a process completed, an approval was requested, a deadline fired) is sent out to notify people, but it is **not stored** in a dedicated audit vault afterward. We also don't yet have retention rules, tamper-evidence (a way to prove records weren't altered after the fact), or the ability to answer cross-cutting questions like "show me every four-eyes approval by this person last quarter."

**Why it matters.** Regulated buyers treat a proper audit trail as a gate, not a nice-to-have. This is the gap most likely to come up in an enterprise or compliance conversation, and it's the one we should close first — the information already exists; it needs a purpose-built home.

## Where we stand at a glance

| Question | Business capability | Maturity |
|---|---|---|
| Can we control what it does? | Governance — four-eyes, roles, permitted-destination controls | **Strong** (one enforcement gap in the lighter running mode) |
| Can we trace the data? | Lineage — versioned records, full input-to-outcome chain | **Foundational — recorded, not yet shown** |
| Can we explain decisions? | Explainability — proposed-vs-approved, who acted | **Foundational — captured, no readable trail or AI rationale** |
| Can we prove it later? | Audit — durable, queryable, tamper-evident record | **Early — de-facto only, needs a purpose-built store** |

## What closing the gaps unlocks

The remaining work is not about inventing new foundations — it's about **surfacing and hardening** what's already there so the platform can withstand outside scrutiny. Concretely, closing these gaps unlocks: readiness for regulated and enterprise customers who require an audit trail as a condition of purchase; faster, cheaper compliance reviews because evidence is a report rather than an investigation; and a clear, demonstrable trust story — "here is exactly what the AI did, what a human decided, and proof it happened" — that becomes a genuine competitive advantage in AI-assisted process automation.

## Bottom line

The hard, foundational work — enforced controls, versioned traceable data, an honest record of AI-proposed versus human-approved decisions — is already built into how Amendia runs. What remains is to give that record a proper home built for auditors, present it in a way a non-engineer can read, and close a small number of enforcement and rationale gaps. That is a focused, well-understood body of work standing on solid ground, not a rebuild.
