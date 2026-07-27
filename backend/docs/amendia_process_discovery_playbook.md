# Amendia — Process Discovery & Documentation Playbook
### A guide for business & operations teams: document your current process, decide what to automate, and produce the BPMN blueprint Amendia will execute

**Author:** Sandeep Kamble

**Who this is for.** Operations leads, process owners, subject-matter experts (SMEs), and the business analysts
who support them. You do **not** need to be a BPMN expert or an engineer to use this playbook — it teaches you
just enough notation, and gives you templates to fill in.

**What it produces.** A thorough, agreed description of how your process works **today**, a clear case for why
you want to move to an agentic way of working, and a **reference BPMN diagram + intake package** that the
Amendia onboarding team turns into a running, auditable process. Everything you capture here maps directly onto
what the onboarding wizard needs — so good discovery here means onboarding is a confirmation, not a rebuild.

**How to use it.** Work through the six phases in order. Phases 1–2 are workshops and interviews; Phases 3–4
are documentation; Phases 5–6 prepare the handoff. Use the templates in the appendix as you go. Budget one to
three weeks for a first process, most of it in Phases 2–4.

---

## The one principle that governs everything

**You cannot automate what you cannot describe.** Amendia is not a black box that "figures out" your process
from vague instructions. It executes a **diagram** — a BPMN model of your process — step by step, exactly as
drawn, pausing for human approval where you tell it to, and recording an audit trail of everything it did. The
quality of the running process is therefore capped by the quality of the diagram. A vague or wishful diagram
produces a vague or wrong automation; a faithful diagram produces a faithful automation.

So the real work is not "learning the tool." It is **making the tacit explicit**: writing down the process that
currently lives in people's heads, in scattered runbooks, and in "we just know to do X when Y happens." That is
the hard, valuable part. This playbook is a method for doing it well.

A second principle follows from the first: **document the real process, not an idealized one.** Capture the
exceptions, the workarounds, the "except when the amount is over £50k" rules, the informal escalations. Those
edge cases are usually where the manual process is slowest and most error-prone — and therefore where agentic
execution delivers the most value. If you smooth them over now, you either lose that value or discover the gaps
painfully at runtime.

---

## What "agentic" changes — and what it deliberately keeps

Before you make the case for change, be precise about what actually changes. Misframing this is the most common
way these programs disappoint.

**What agentic execution changes.** The routine, high-volume, rules-and-lookups work that today consumes your
team's hours — gathering information from systems, enriching a case, drafting an instruction, screening a party,
applying a repair, notifying counterparties, recording the outcome — is done by software agents, consistently,
around the clock, in seconds rather than hours, with every step logged. Your people stop being the *engine* of
the process and become its *judgment and control*.

**What agentic execution deliberately keeps.** Amendia is built so that **a step with real-world consequences
cannot happen without a human authorization** — releasing a payment, sending an external message, moving money.
The four-eyes principle (the person who prepared an action cannot be the one who approves it) is enforced by the
platform, not left to discipline. Accountability stays with named human roles. Judgment on genuinely ambiguous
cases stays human. In other words: agentic execution removes the *toil*, not the *control*. When you explain
this to risk, compliance, and audit stakeholders, lead with it — it is usually what unblocks them.

Holding both of these clearly in mind is what lets you draw an honest diagram: most steps become agent
capabilities, the money-moving and outward-facing steps sit behind human approval gates, and the decisions
become explicit rules rather than folklore.

---

## Phase 1 — Frame the case for change

Do this **first**, before you document a single step, because it sets the scope and the success criteria for
everything after. It is a short, senior-sponsored workshop, not a long study.

### 1.1 Name the process and its trigger

State, in one sentence, **what event starts this process and what outcome ends it**. For example: *"A wire
transfer arrives that cannot be applied to a beneficiary account (an 'unable-to-apply' exception); the process
ends when the payment is either repaired and released, or returned to the originator."* A crisp
trigger-to-outcome sentence is the boundary of your scope. Everything inside it is in; everything outside is a
different process.

### 1.2 Describe the pain of the current way

Be concrete and, where you can, quantitative. The strongest cases name real numbers even if they are estimates.
Capture:

- **Volume & cycle time** — how many cases per day/week; how long each takes end to end; how much of that is
  waiting versus working.
- **Cost & capacity** — how many FTEs, or fraction of, are consumed; what the backlog looks like at peak.
- **Errors & rework** — how often something is done wrong, missed, or has to be redone; the downstream cost when
  it is.
- **Compliance & risk** — where the process depends on someone remembering to do a control (a screening, an
  approval); where the audit trail is thin or reconstructed after the fact.
- **Key-person dependency** — which steps only one or two people really know how to do; what happens when
  they're on leave.
- **Experience** — the parts your team finds most tedious, and the parts customers or counterparties find
  slowest.

### 1.3 State the benefits you expect — and how you'll measure them

For each pain point, name the improvement you expect and the metric you'll track. This becomes your business
case and, later, your proof. Common agentic benefits, framed honestly:

| Benefit | What it looks like | How to measure it |
|---|---|---|
| **Speed** | Cases resolve in seconds/minutes of agent work; humans touch only approvals | Median & 95th-percentile cycle time, before vs after |
| **Consistency** | Every case follows the same steps and rules; no skipped controls | Rework rate; control-completion rate |
| **Auditability** | Every step, input, output, and approval is logged automatically | Time to produce an audit trail; audit findings |
| **Capacity & scale** | Volume spikes absorbed without proportional headcount | Cases per FTE; backlog at peak |
| **Availability** | Runs 24/7; no queue building overnight | Aging of the queue |
| **Focus** | People spend time on judgment and exceptions, not lookups and typing | % of human time on approvals/exceptions vs data-gathering |
| **Resilience** | Process knowledge lives in the diagram, not one person's head | Bus-factor; onboarding time for new staff |

Resist over-claiming. Agentic execution does **not** eliminate human review of consequential actions, does not
remove accountability, and does not make judgment calls disappear — it concentrates human effort where it
matters. A business case that promises "zero humans" will fail its own success test and lose the room's trust.

### 1.4 Confirm sponsorship and the SMEs

Name the accountable process owner, the SMEs who actually perform the work (you will interview and shadow them),
and the control functions (risk, compliance, audit) who must be comfortable with the target. Get their time
committed now.

**Phase 1 output:** a one-page *Process Charter* (template in the appendix) — trigger-to-outcome scope, the pain
with numbers, the expected benefits with metrics, and the people.

---

## Phase 2 — Discover the as-is process

Now find out how the work is *really* done. The goal is a complete, agreed, step-by-step picture — before any
diagramming.

### 2.1 Gather what already exists

Collect current standard operating procedures (SOPs), runbooks, work instructions, checklists, screenshots,
email templates, and any system of record the team uses. These are your starting material — but treat them as a
draft: documented procedures are often out of date or describe the ideal, not the actual. Your job is to
reconcile them with reality.

### 2.2 Interview and shadow the people who do the work

The single most valuable activity. For each distinct role in the process:

- **Walk a real case with them, end to end.** "A case just landed — show me exactly what you do." Watch which
  systems they open, what they copy where, what they check, who they hand off to, and — crucially — **the
  judgment calls they make and the rules they apply** ("if the beneficiary name is a close match I repair it;
  if it's off by more than a couple of characters I request information").
- **Ask about the exceptions.** "What makes a case hard? When do you escalate? What's the weirdest thing that
  can happen?" The exception paths are where the real complexity lives and where documentation is usually
  weakest.
- **Ask about the rules.** Every "it depends" hides a rule. Push until you can write it as a testable
  condition ("repairable when the beneficiary match is exact **and** the amount is under the auto-repair limit").
- **Ask about the controls and approvals.** Who has to sign off on what, and why? What can't the same person do
  twice? What are the SLAs, and what happens when they're breached?

Shadow more than one person per role if you can — you'll discover that "the process" is actually several
variations, and you need to decide which is canonical.

### 2.3 Reconcile into a single agreed narrative

Bring the SOPs and the interview findings together into one plain-language, numbered walkthrough of the process
— the happy path first, then each exception and branch. Circulate it and get the SMEs and the process owner to
agree it is accurate, including the parts that contradict the written SOPs. Disagreements surfaced here are gold:
they usually mean the process genuinely varies and you must decide the standard.

**Phase 2 output:** an agreed, plain-language *Process Narrative* — the happy path plus every branch and
exception, with the rules and approvals written as testable conditions. This is what you will diagram in Phase 4.

---

## Phase 3 — Capture the eight dimensions Amendia needs

Amendia executes a process along eight dimensions. Capturing each one explicitly during discovery is what makes
the later BPMN model complete and the onboarding smooth. Work through them against your Phase 2 narrative; the
appendix has a template for each.

**1 · Steps (the activities).** Every discrete unit of work: "enrich the payment," "assess repairability,"
"draft the repair," "apply the repair." For each, note *what it does*, *what it needs to start*, and *what it
produces*. Aim for steps that are single-purpose — if a step "does three things," it's probably three steps.

**2 · Roles & personas (who does what).** The distinct actors: an operations analyst, a four-eyes approver, a
supervisor, and — new here — **the automation itself** (the agent). Group your steps by who performs them.
These groupings become **swimlanes** in your diagram, and Amendia turns each lane into a **role** it enforces at
runtime (only someone with that role can act on that step). Name roles by function, not by person.

**3 · Systems touched (the boundaries).** Every external system or party the process interacts with: the core
banking system, a sanctions-screening provider, counterparty banks, a payments rail. In BPMN these are **pools**
(external participants). In Amendia, each interaction with an external system becomes a **capability** — a small,
well-defined tool the agent calls (e.g. "fetch payment details," "screen a party," "release the payment"). List
them; they become your capability inventory.

**4 · Data & artifacts (what flows).** The information each step reads and writes: the incoming exception
details, an "investigation dossier," a "repair verdict," a "screening result," a payment-release
acknowledgement. Amendia treats each as a **typed artifact** — a defined shape of data that is validated at
every step and shown to humans at approval time. For each step, note what data it consumes and what it produces.
Pay special attention to any field a **decision** depends on (see dimension 6): those fields must always be
present.

**5 · Approvals & controls (the human gates).** Where a human must review, approve, or perform a step. Amendia
offers a graded set of oversight levels; decide which each step needs:

| Oversight level | Meaning | Typical use |
|---|---|---|
| **None** | The agent runs autonomously | Read-only investigation, enrichment, recording |
| **Review after** | The agent acts; a human reviews (and can edit/reject) the result | Drafting an instruction, an assessment |
| **Approve result** | A human approves the produced result before it's used | A screening verdict, a recommendation |
| **Approve actions** | A human authorizes a real-world action *before it happens* | Releasing a payment, sending a message — anything with external consequences |
| **Manual** | A human performs the step; the agent may pre-draft | A phone call, a manual system entry |

The rule Amendia enforces: **any step with a real-world side effect (money movement, an outward message, a
system-of-record write) must sit behind "approve actions" or stricter.** So as you capture steps, mark each one
**read-only** (just reads/computes) or **side-effectful** (changes the outside world) — this single distinction
drives the whole control model. Also capture **four-eyes / separation-of-duties** rules: which pairs of steps
must be done by *different* people (e.g. whoever drafts a repair cannot be the one who approves it). Amendia
enforces these automatically.

**6 · Decisions (the branch points).** Every point where the process forks based on the data: "is the payment
repairable?", "did screening return a hit?", "is the amount over the auto-approval limit?" Capture the
**question**, the **data field** it reads, and the **branches** it leads to. Simple two/three-way forks become
**gateways** in the diagram. Where a decision is really a **table of rules** ("if status = X and amount < Y then
verdict = repairable"), capture it as a table — Amendia can execute it directly as a **decision table**, which
means your business rules live as an auditable table anyone can read, not as buried code.

**7 · Timing & escalation (the clocks).** Any deadlines or SLAs: "an approval must happen within 4 hours or it
escalates to a supervisor," "if the sanctions result doesn't come back in 30 minutes, proceed on the timeout
path." Capture the duration and what happens when it elapses. These become **timers** and **escalation paths**.

**8 · Exceptions & undo (what goes wrong, and rollback).** Two kinds:
- **Anticipated business outcomes that aren't the happy path** — "the payment was rejected by the rail," "the
  screening returned a hit," "the counterparty sent insufficient information." These are *modeled* outcomes the
  process handles with a defined branch, not failures. Capture each and where it routes.
- **Undo / compensation** — if a later step fails after an earlier step already did something real, does
  anything need to be reversed? ("We released the payment, then a downstream check failed — we must reverse the
  release.") Capture which actions have a real reversal ("undo") and what it is. Amendia can run these undos in
  reverse order, through the same approval gates.

**Phase 3 output:** eight filled-in inventories (steps, roles, systems, artifacts, approvals+SoD, decisions,
timers, exceptions+undo). Together they are the substance of your process; the diagram in Phase 4 is their
picture.

---

## Phase 4 — Model it in BPMN

BPMN (Business Process Model and Notation) is the standard picture-language for processes. You need only a
handful of shapes. This section is a practical primer; the appendix has a one-page quick reference. **Use any
BPMN 2.0 tool** (many are free) that can export a `.bpmn` file — that file is what Amendia ingests.

### 4.1 The shapes you need

- **Start event** (thin circle) — how the process begins (your trigger from Phase 1).
- **End event** (thick circle) — how it ends. You'll usually have several (resolved, returned, rejected).
- **Task** (rounded rectangle) — one step. Amendia distinguishes a few kinds: a **service task** (an agent
  capability does it), a **user task** (a human does it), a **business-rule task** (a decision table evaluates
  it), a **send/receive task** (a message goes out / is awaited). For discovery, draw each step as a task and
  label it; you'll classify the kind with the onboarding team.
- **Gateway** (diamond) — a decision or a merge. An **exclusive** gateway (diamond with an X) takes exactly one
  branch based on a condition. Label the branches with their conditions ("repairable," "unrepairable," "needs
  info").
- **Sequence flow** (solid arrow) — the order of steps within your process.
- **Swimlane** (a horizontal "lane" in a box) — one per **role**. Put each task in the lane of whoever performs
  it. Add a lane for **the automation/agent**. This is how Amendia infers your roles.
- **Pool** (a big box, usually separate) — an **external participant/system** (the core banking system, the
  sanctions provider). Interactions with a pool are drawn as **message flows** (dashed arrows). These document
  the system boundaries and become your capabilities.
- **Events on the flow** — a **timer** (clock icon) for an SLA/deadline, an **error** (lightning icon) for a
  modeled business failure, a **message** (envelope) for waiting on an external reply. Attach a timer or error
  to the **edge of a task** (a "boundary event") to mean "if this happens while the task is running/waiting,
  take this other path" — e.g. an SLA timer on an approval that escalates to a supervisor.
- **Sub-process** (a task with a small ⊞) — a group of steps you want to collapse into one box for readability,
  or a reusable procedure.

### 4.2 How to draw it well

- **Start with the happy path, left to right.** Get the main success flow clear first, then add the branches
  and exceptions.
- **One lane per role; put every task in a lane.** If a task doesn't fit a lane, you've found a missing role.
- **Label every gateway branch with its condition** in plain, testable terms. A branch with no condition is
  ambiguous.
- **Make decision-driving data explicit.** If a gateway asks "repairable?", make sure the step before it
  produces a clear "repairable / unrepairable / needs-info" result. Amendia requires the field a gateway reads
  to always be present.
- **Draw the exception paths, not just the happy path.** The rejected/returned/escalated ends are part of the
  process.
- **Keep tasks single-purpose and named as verbs** ("Assess repairability," not "Repairability").
- **Don't encode automation details in the diagram.** The diagram is the *business* process — who does what, in
  what order, with what decisions and controls. *How* an agent performs a step (which system, which model) is
  captured separately as capabilities. Keep the diagram about the business.

### 4.3 One diagram, faithfully complete

You may have heard that automation tools force you to strip a diagram down to a simplified "executable" version.
**Amendia does not.** It ingests your **full, faithful** BPMN — swimlanes, pools, message flows, timers, error
paths, sub-processes and all — and executes the parts that are executable while treating lanes and external
pools as the documentation and role/system information they are. So draw the **real** process once, completely.
The richer and more honest the diagram, the more Amendia can infer for you at onboarding (roles from lanes,
system integrations from pools, four-eyes candidates from cross-lane approval pairs) — and the less you fill in
by hand.

**Phase 4 output:** a **reference BPMN diagram** (`.bpmn` file) of your real process — the blueprint Amendia
will execute.

---

## Phase 5 — Identify what becomes automation

With the diagram drawn and the eight dimensions captured, classify each task. This is a working session between
your SMEs and the Amendia onboarding team, but you can pre-fill most of it.

**For each task, decide its kind:**

- **Agent capability (service task).** The routine, describable work — gather, enrich, assess, draft, screen,
  apply, notify, record. Most tasks. For each, note the **external system or tool** it uses (this becomes a
  *capability* — often a small connector to that system) and, critically, whether it is **read-only** or
  **side-effectful**. Side-effectful ones will require an approval gate.
- **Human step (user task).** Genuine human judgment or a physical/manual action — a four-eyes approval, a phone
  call, a manual entry the agent can't make. Note the **role** and the **oversight level**.
- **Decision (business-rule task / gateway).** A rules-based branch. If it's a small fork, it's a gateway on the
  diagram. If it's a table of rules, capture the **decision table** — inputs, the rule rows, and the verdict —
  so it can be executed directly and read by anyone.

**Then set the controls.** For every side-effectful capability, confirm the human gate ("approve actions" or
stricter). For every sensitive pair, confirm the four-eyes rule. For every deadline, confirm the timer and its
escalation. These aren't afterthoughts — in Amendia they are *validated configuration*, so getting them right
here is getting the control model right.

**A useful sanity check — the automation candidate test.** A step is a strong candidate for an agent capability
when it is: high-volume, rules-or-lookups based, describable as clear inputs → clear outputs, and reads from or
writes to systems you can connect to. A step should **stay human** when it needs genuine judgment on ambiguous
cases, carries accountability that must rest with a person, or is a required control. Most processes are ~70–90%
capability tasks with a few well-placed human gates — that ratio *is* the value.

**Phase 5 output:** an annotated task list — each task classified (capability / human / decision), each
capability marked read-only or side-effectful with its system, each human step's role and oversight level, each
decision's rules, all controls confirmed.

---

## Phase 6 — Assemble the intake package & check readiness

Package everything for handoff to onboarding. The intake package is simply your Phase 1–5 outputs, organized.
Because each piece was captured against Amendia's model, the onboarding team can move through the wizard mostly
confirming your work.

**The intake package contains:**

1. The **Process Charter** (Phase 1) — scope, pain, benefits, metrics, people.
2. The **Process Narrative** (Phase 2) — the agreed plain-language walkthrough.
3. The **reference BPMN** (`.bpmn`, Phase 4).
4. The **eight inventories** (Phase 3) — steps, roles, systems, artifacts, approvals+SoD, decisions, timers,
   exceptions+undo.
5. The **annotated task classification** (Phase 5) — capability/human/decision, read-only/side-effectful,
   oversight levels, decision tables.
6. The **triage definition** — which incoming cases *this* process should handle (the conditions that route a
   case here), so it doesn't overlap with another process.

**Readiness checklist — you're ready to onboard when:**

- [ ] The trigger-to-outcome scope is agreed and written in one sentence.
- [ ] The reference BPMN reflects the **real** process — happy path **and** every branch/exception — and every
      task sits in a role's swimlane.
- [ ] Every gateway branch has a plain, testable condition, and the field each decision reads is always produced
      by an earlier step.
- [ ] Every task is classified capability / human / decision.
- [ ] Every capability is marked read-only or side-effectful and names the system it uses.
- [ ] Every side-effectful step has a human approval gate; every sensitive pair has a four-eyes rule.
- [ ] Every deadline/SLA has a timer and an escalation path.
- [ ] Every anticipated non-happy outcome (rejected, hit, insufficient info) has a defined branch, and every
      action that needs reversing has a named undo.
- [ ] The data each step reads/writes is described, and decision-driving fields are always present.
- [ ] The triage conditions that route cases to this process are defined and don't collide with another process.
- [ ] The SMEs and the process owner have **signed off** that the package is accurate.

When those are true, hand the package to the Amendia onboarding team. Onboarding (covered in the *Process
Onboarding Guide*) is then largely a matter of pointing the wizard at your BPMN, confirming the roles and
bindings it infers from your lanes, connecting the capabilities to your systems, and activating — most of which
is confirmation of decisions you already made here.

---

## Worked example — a wire-transfer exception

To make it concrete, here is the shape of a real example (the "unable-to-apply" wire exception) as it comes out
of this playbook.

**Charter.** *Trigger:* a wire arrives that can't be applied to a beneficiary. *Outcome:* repaired-and-released,
or returned to originator. *Pain:* ~X cases/day, ~Y minutes each, mostly analysts gathering data across three
systems; screening sometimes skipped under load (a control risk); audit trail reconstructed from emails.
*Benefits:* cut cycle time from ~Y minutes to minutes of agent work + one approval; guarantee screening runs
every time; automatic audit trail.

**Roles (swimlanes).** *AI Agent* (autonomous investigation/drafting), *Ops Analyst* (reviews agent output,
handles information requests), *Ops Approver* (four-eyes approver of money-moving actions), *Supervisor*
(SLA escalations).

**Systems (pools).** Core banking (fetch payment), sanctions provider (screen party), payment rails
(release/return), counterparty banks (messages). Each becomes a capability.

**Happy path (tasks).** Enrich & investigate payment *(agent, read-only, none)* → Assess repairability *(agent,
read-only, review-after)* → **decision: repairable?** → Draft repair *(agent, read-only, review-after)* →
Approve repair *(human, four-eyes)* → Sanctions re-screen *(agent, read-only, approve-result)* → Apply repair &
release *(agent, **side-effectful**, approve-actions)* → Notify parties *(agent, side-effectful,
approve-actions)* → Record resolution *(agent, read-only, none)* → **End: resolved**.

**Branches & exceptions.** *Unrepairable* → draft & approve a return → execute return → **End: returned**.
*Needs info* → request information (human) → loop back to assess. *Screening hit* → a modeled business outcome
routing to a compliance-hold branch. *Approval SLA breach* → timer escalates to Supervisor.

**Controls.** Apply/Notify/Execute-return are side-effectful → all gated at approve-actions. Draft-repair and
Approve-repair must be different people (four-eyes); likewise draft-return and approve-return.

**Decision as a table.** "Repairable?" is a rules table: inputs = beneficiary-match quality + amount; rows map
to *repairable / unrepairable / needs-info*. Captured as a table, executed directly, readable by any auditor.

That package — charter, narrative, BPMN, inventories, classification, triage — is exactly what makes onboarding
this process fast and faithful.

---

## Appendix A — BPMN quick reference (the shapes you'll use)

| Shape | Looks like | Means | Amendia mapping |
|---|---|---|---|
| Start event | thin circle | process begins | the trigger; cases are routed here by triage |
| End event | thick circle | an outcome | resolved / returned / rejected … |
| Task | rounded rectangle | one step | agent capability, human step, or decision |
| Exclusive gateway | diamond with X | one-of-N branch | a decision; label each branch's condition |
| Sequence flow | solid arrow | step order | the executed path |
| Swimlane | horizontal lane | a role/actor | a pack role Amendia enforces |
| Pool | separate box | external system/party | a capability (connector) |
| Message flow | dashed arrow | talk to a pool | an external interaction |
| Timer (boundary) | clock on a task edge | a deadline while a step runs/waits | SLA + escalation path |
| Error (boundary) | lightning on a task edge | a modeled business failure | a handled outcome branch (e.g. rejected) |
| Sub-process | task with ⊞ | a collapsed/reusable group | executed inline |

## Appendix B — Intake templates (copy and fill)

**Process Charter (1 page):** Process name · Trigger (one sentence) · Outcomes · Current pain (volume, cycle
time, cost, errors, compliance, key-person) with numbers · Expected benefits + metric per pain point ·
Accountable owner · SMEs · Control functions.

**Step inventory:** for each step — name (verb) · what it does · inputs it needs · outputs it produces · role
that performs it · read-only or side-effectful · system(s) used.

**Role map:** role name (by function) · what they do in this process · which steps · what only they can do
(four-eyes constraints).

**Systems inventory:** system/party · what the process needs from it (fetch / screen / release / send) ·
read-only or side-effectful.

**Artifact inventory:** data object (e.g. "repair verdict") · produced by which step · consumed by which
step(s) · key fields · which fields a decision depends on (must always be present).

**Approvals & SoD:** step · oversight level (none / review-after / approve-result / approve-actions / manual) ·
role that approves · four-eyes pairs (step A and step B must be different people).

**Decision catalog:** decision question · data field(s) it reads · branches/verdicts · if a table: inputs, rule
rows, and the verdict per row.

**Timer & escalation catalog:** step/gate · deadline (duration) · what happens on breach (escalate to whom /
take which path).

**Exception & undo catalog:** anticipated non-happy outcome · where it routes · any earlier action that must be
reversed on later failure, and the reversal ("undo") for it.

**Triage definition:** the conditions that route an incoming case to *this* process (e.g. exception type +
message type + reason codes) · priority relative to other processes.

## Appendix C — Glossary (business terms)

**Process pack** — the packaged, versioned process Amendia runs (your BPMN + its execution details).
**Capability** — a specific competence an agent uses to do a step, often a connector to one of your systems.
**Artifact** — a defined shape of data a step reads or writes, validated at every step.
**Swimlane / role** — an actor in the process; Amendia enforces that only that role can act on its steps.
**Pool** — an external system or party the process interacts with. **Gateway** — a decision/branch point.
**Decision table** — business rules written as a readable table Amendia executes directly.
**HITL (human-in-the-loop)** — the graded human-oversight levels (none → approve-actions → manual).
**Side-effectful** — a step that changes the outside world (moves money, sends a message); always gated.
**Four-eyes / separation of duties** — the same person can't both prepare and approve a sensitive action.
**Timer / SLA** — a deadline and what happens when it's missed. **Boundary event** — a timer/error attached to
a step's edge, giving it an alternate path. **Compensation / undo** — reversing a completed action when a later
step fails. **Triage** — the rules that route an incoming case to the right process.

---

*This is a living playbook. As your team documents more processes, refine the templates with what you learn. The
better the discovery, the more faithful — and the more valuable — the automation.*
