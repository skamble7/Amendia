# Amendia — Worked Scenario: The Wire-Transfer Exception, from Manual to Agentic
### One process, end to end — documented with the Discovery Playbook, designed as an agentic process, onboarded through the wizard, and executed on the runtime

**Author:** Sandeep Kamble

---

## 0 · What this scenario is

This is a single, concrete walk through the **entire Amendia journey** for one real process: the *unable-to-apply
wire transfer exception*. It shows the four moments in sequence — the business **documents** today's manual
process with the *Process Discovery & Documentation Playbook*, we **design** the agentic version, we **onboard**
it through the wizard, and the runtime **executes** it. The point is that none of this is hypothetical: the MCP
server that backs the agent steps (`mcp_stub/`) is real, the onboarding wizard authors the full construct set,
and the agent-runtime executes it — so the loop *document → onboard → execute* actually closes.

Two diagrams accompany this document: **`wire-repair-manual.asis.bpmn`** (the current manual process) and
**`wire-repair-agentic.tobe.bpmn`** (the agentic target). Both are valid, laid-out BPMN 2.0 that render in the
wizard and — for the agentic one — onboard and run.

---

## 1 · Frame the case for change (Playbook Phase 1 — the Charter)

**Trigger → outcome.** A wire transfer arrives that **cannot be applied** to a beneficiary account (a name/
account mismatch, missing remittance detail, or a closed account — camt.026 semantics). The process ends when
the payment is either **repaired and released**, or **returned** to the originator (pacs.004).

**The pain today (with the numbers the ops lead put on it).**

| Pain | Today |
|---|---|
| Volume & cycle time | ~120 exceptions/day; **~35 min each**, most of it swivel-chairing across three systems |
| Cost & capacity | ~6 FTE analysts; a **200+ item backlog** builds overnight and at month-end peaks |
| Errors & rework | Repairs occasionally keyed wrong; **sanctions re-screening is sometimes skipped under load** — a control gap |
| Compliance & audit | The trail is **reconstructed from emails** after the fact; slow and incomplete |
| Key-person risk | Two analysts really know the edge cases; **backlog spikes when they're on leave** |

**The benefits we expect, and how we'll measure them.**

| Benefit | Target | Metric |
|---|---|---|
| Speed | Seconds of agent work + one approval, vs 35 min | Median & p95 cycle time |
| Consistency | Screening runs **every** time; no skipped control | Control-completion rate; rework rate |
| Auditability | Every step, input, output, approval logged automatically | Time-to-produce an audit trail |
| Capacity | Absorb peaks without adding headcount | Cases per FTE; overnight backlog |
| Focus | Analysts spend time on judgment, not lookups | % human time on approvals vs data-gathering |

**Deliberately kept (what agentic does *not* remove).** Money-moving and outward-facing steps stay behind a
**human approval**; the **four-eyes** rule (the preparer can't approve their own repair) is enforced by the
platform; accountability stays with named roles. This is what unblocks Risk and Compliance — it removes the
toil, not the control.

**People.** Process owner: Head of Payment Operations. SMEs: two senior analysts (Riya, Priya) + an approver
(Marcus). Control functions: Sanctions Compliance, Internal Audit.

---

## 2 · Document the current manual process (Playbook Phases 2–3)

### 2.1 The analyst's day (the as-is narrative)

An exception lands in the ops queue. An analyst **pulls the payment** from core banking, **investigates** — checks
the beneficiary name against the account, looks at payment history, decides whether it's a repairable typo, a
genuine return, or something needing more information. If repairable, they **draft the repair**, get a colleague
to **approve it (four-eyes)**, **re-screen** the beneficiary for sanctions by hand, **key the repair into the
rail** and release, **notify** the originator and beneficiary bank by email/SWIFT, and **record** the outcome in
a spreadsheet. If unrepairable, they draft a **return (pacs.004)**, get it approved, and execute it. If
information is missing, they **chase it** by email/phone and re-assess when it comes back.

### 2.2 The as-is process — *Figure 1*

*(`wire-repair-manual.asis.bpmn`)* — two swimlanes (Ops Analyst, Ops Approver); **every step is human.** The
manual re-screen and the spreadsheet record are exactly the control-gap and audit-gap the charter named.

![As-is manual process](asis.png)

### 2.3 The eight dimensions, as the business captured them

**1 · Steps** — pull, investigate/assess, draft repair, approve, re-screen, apply/release, notify, record;
draft return, approve return, execute return; chase info. **2 · Roles** — Ops Analyst (does most steps), Ops
Approver (four-eyes). **3 · Systems** — core banking (fetch), sanctions provider (screen), payment rails
(release/return), counterparty banks (messages). **4 · Data** — the exception details, an investigation view, a
repair verdict, a screening result, release/return acknowledgements, the resolution record. **5 · Approvals &
SoD** — four-eyes on both the repair and the return (drafter ≠ approver); apply/notify/execute move money or go
outward → they must be authorized. **6 · Decisions** — *repairable?* → repairable / unrepairable / needs-info,
based on beneficiary-match quality + amount. **7 · Timing** — approvals should clear within ~4 h or escalate
(informal today). **8 · Exceptions & undo** — a **screening hit** → compliance hold; a **rail rejection** →
return path; if a release ever went out wrongly, it would need reversing.

That last column is the gold: today the SLA and the screening-hit handling are *informal* — which is precisely
where the manual process is slowest and most risky.

---

## 3 · Design the agentic process (Playbook Phases 4–5)

### 3.1 Classify each step

| Step | Kind | Read-only / side-effectful | Oversight |
|---|---|---|---|
| Enrich & investigate | agent capability | read-only | none (autonomous) |
| Assess repairability | **decision table** | — | review of the verdict |
| Draft repair | agent capability | read-only | review-after |
| **Approve repair** | **human (four-eyes)** | — | approve-result |
| Sanctions re-screen | agent capability | read-only | approve-result |
| **Apply repair & release** | agent capability | **side-effectful** | **approve-actions** |
| **Notify parties** | agent capability | **side-effectful** | **approve-actions** |
| Record resolution | agent capability | read-only | none |
| Draft / Execute return | agent capability | read-only / **side-effectful** | review / **approve-actions** |
| Obtain missing info | **human** | — | manual |

The pattern is the value: **~80% agent capabilities, a few well-placed human gates** exactly on the money-moving
and four-eyes steps.

### 3.2 The agentic target — *Figure 2*

*(`wire-repair-agentic.tobe.bpmn`)* — four swimlanes (**AI Agent**, Ops Analyst, Ops Approver, Supervisor). The
agent lane carries the routine work; approvals sit in the Approver lane; the needs-info step is the Analyst's;
and two things the manual process only did *informally* are now **first-class**: an **SLA timer** on the repair
approval that **escalates to a Supervisor** after 4 h, and a **sanctions-hit error path** that routes to a
**compliance hold**. Four outcomes: resolved, returned, escalated, compliance-hold.

![To-be agentic process](tobe.png)

### 3.3 The decision, as a table

"Repairable?" is not code — it's an auditable table anyone can read (authored directly in the wizard, ADR-037):

| gpi_status | beneficiary_match | amount | → repair_verdict |
|---|---|---|---|
| resolved | exact | `< 50,000` | repairable |
| resolved | close | any | needs_info |
| rejected | — | — | unrepairable |
| — | none | — | needs_info |

`repair_verdict` is a **required** field — it's what the gateway branches on.

### 3.4 The capabilities are real — `mcp_stub`

The agent steps aren't hand-waving: they're the ten tools the **`mcp_stub/servers/wire_transfer_exception`**
server already exposes over streamable HTTP — `enrich_investigation`, `assess_beneficiary`, `draft_rfi`,
`draft_repair`, `screen_party`, `apply_repair`, `notify_parties`, `record_resolution`, `draft_return`,
`execute_return` — each with declared input/output schemas, the three action tools flagged side-effectful. The
wizard introspects that server and turns each tool into a capability + two artifact schemas.

---

## 4 · Onboard it (the wizard)

With the reference BPMN and the intake package in hand, onboarding is largely **confirming** what the wizard
infers. Step by step, grounded in what the platform actually does:

**1 · Basics.** `pack_key: wire-repair-agentic`, `version: 1.0.0`, domain `wirefix` (so it never collides with
the seeded `payment` catalogue).

**2 · Attach the BPMN.** The wizard ingests the full reference (classify-don't-reject): **coverage** shows the
executable elements (tasks, gateway, decision, boundaries) as *executable* and the lanes/pools as *documented*.
Crucially it **infers from the diagram** (ADR-045): four **roles from the lanes**, **binding scaffolds** with a
lane-driven HITL suggestion per task (AI Agent → `none`, Ops Approver → `approve_actions`, Supervisor →
escalation), the **four-eyes SoD candidates** (draft/approve pairs in different lanes), the **gateway variable**
(`repair_verdict`), and a **decision-table candidate** on the `businessRuleTask`.

**3 · Capabilities.** Point the wizard at the `mcp_stub` server → introspect → the ten tools come back
compliant → stage `cap.wirefix.*` (each with its input/output artifact), marking `apply_repair`,
`notify_parties`, `execute_return` **side-effectful**. Author the **repairability decision as a table** inline
(the candidate from step 2), staging a `decision` capability — no code (ADR-046).

**4 · Bindings.** One row per task, **pre-filled** from the inference: agent tasks bound to their capabilities;
the two approvals bound to the **Ops Approver** role; obtain-info to the Ops Analyst. The lane-driven HITL is
already set — and the **side-effect floor holds**: `apply_repair`/`notify` are forced to `approve_actions`
regardless of lane (the platform enforces this; ADR-040-era guard).

**5 · Triage.** Route the right cases here: `exception_type = unable_to_apply` AND `msg_type` starts `pacs.008`
AND `reason_codes` intersects a test code (`AG01`), at a priority that doesn't shadow the seeded pack.

**6 · Policies.** The **gateway variable** `beneficiary.repair_verdict` (resolves to the decision's required
output field); the two **four-eyes SoD** pairs; **roles** with `role_meta` **descriptions pre-filled from the
lane personas** ("Four-eyes approver — authorizes side-effectful actions", etc.).

**7 · Assemble & activate.** The **7-stage validator** dry-runs clean against the staged artifacts/capabilities;
commit registers artifacts → capabilities → pack → BPMN → validate → **activate** (pinning versions, writing the
resolution sidecar). The pack is live.

Everything the wizard did here — the full element set, the message/call executors, the lane-persona pre-fills,
the inline decision authoring — is exactly what the three onboarding-catchup tracks (ADR-044/045/046) delivered.

---

## 5 · Execute it (the runtime)

A test exception carrying reason code `AG01` is generated. The ingestor's `/resolve` matches
`wire-repair-agentic@1.0.0`; the agent-runtime loads the pinned pack, compiles the BPMN + manifest to a graph,
and runs it — pausing at every human gate, recording every step:

1. **Enrich** *(agent, autonomous)* — calls `enrich_investigation`; writes an investigation dossier. Logged.
2. **Assess repairability** *(decision table)* — evaluates the table over the dossier → `repair_verdict =
   repairable`. The gateway takes the **repairable** branch.
3. **Draft repair** *(agent, review-after)* — `draft_repair` produces a repair instruction; Riya reviews it.
4. **Approve repair** *(human, four-eyes)* — the instance **pauses** as a HITL task for the **Ops Approver**.
   Marcus approves. **Separation of duties blocks Riya from approving her own draft** — the platform enforces
   it. *(Had it sat unactioned 4 h, the **SLA timer** would have escalated to a Supervisor.)*
5. **Sanctions re-screen** *(agent, approve-result)* — `screen_party` returns `clear`; the result is approved
   and the flow continues. *(A `hit` would raise a **modeled business error** → the **compliance-hold** branch;
   the instance stays running on the handled path, not a crash — ADR-030/035.)*
6. **Apply repair & release** *(agent, side-effectful, approve-actions)* — the instance **pauses again**: this
   moves money. Marcus authorizes; `apply_repair` releases the payment and returns an **acknowledgement**
   (`action_id`) that anchors the audit record.
7. **Notify parties** *(agent, side-effectful, approve-actions)* — approved; `notify_parties` sends the
   messages, returns acknowledgements.
8. **Record resolution** *(agent, autonomous)* — `record_resolution` writes the evidence bundle. **End: Exception
   resolved.**

The whole run is one auditable instance: **every input, output, and approval is captured automatically** — the
audit trail the manual process reconstructed from emails now exists by construction. The two human touches
(approve repair, approve release) are exactly the control points the business insisted on keeping.

---

## 6 · What the business got — before vs after

| | Before (manual) | After (agentic) |
|---|---|---|
| Cycle time | ~35 min of analyst work | seconds of agent work + 2 approvals |
| Screening | sometimes skipped under load | **runs every time**, on the modeled path |
| Approvals | four-eyes by discipline | four-eyes **enforced by the platform** |
| SLA / escalation | informal | **timer → Supervisor**, modeled |
| Audit trail | reconstructed from emails | **automatic**, per step |
| Analyst time | lookups & typing | judgment & exceptions |

Same controls, a fraction of the toil — and the edge cases the manual process handled informally (SLA,
screening-hit) are now first-class, modeled, and audited.

---

## 7 · The artifacts this scenario produced

- **`wire-repair-manual.asis.bpmn`** — the current manual process (Figure 1), renderable BPMN 2.0.
- **`wire-repair-agentic.tobe.bpmn`** — the agentic target (Figure 2), the file that onboards and runs.
- **`mcp_stub/servers/wire_transfer_exception`** — the real MCP server backing the agent capabilities (already
  implemented: 10 tools, streamable HTTP, schema-valid).
- Companion guides: the *Process Discovery & Documentation Playbook* (how a business produces the inputs above)
  and the *Process Onboarding Guide* (how the wizard turns them into a live pack).

The loop is closed: a business documents its process, we shape it into an agentic one, the wizard onboards it,
and the runtime executes it — with the controls the business cares about kept, and the toil removed.
