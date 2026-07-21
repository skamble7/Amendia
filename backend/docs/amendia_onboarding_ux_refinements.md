# Amendia — Onboarding Wizard: UX Refinements (running log)

A living log of operator-testing feedback on the onboarding wizard and how each item is addressed. Captured as
Sandeep walks the full wizard with the corrected `wire-repair-agentic` reference. Each item → a status + the
prompt/ADR that lands it.

## Batch 1 — 2026-07-21

| # | Step | Feedback | Status | Addressed by |
|---|---|---|---|---|
| 1 | Basics | Looks good. | ✅ no change | — |
| 2 | BPMN | Fine, but the upload/paste input stays fully expanded after parse; enclose it in a **collapsible section** that collapses on a successful drop/parse so the coverage + diagram below come into focus. | ✅ shipped | batch-1 Change 1 — `BpmnStep` `collapsed` state + `scrollIntoView` to coverage; "Replace / edit" re-expands |
| 3 | Capabilities | The "your diagram expects capabilities here" ids **are inferred** (confirmed — `capability_candidates`, `cap.<domain>.<task>`). | ✅ answered | — |
| 4 | Capabilities | "Reuse existing capabilities" eager-loads the **whole catalog** — doesn't scale as capabilities grow. Make it **on-demand**: a button → search dialog to find & select a capability. Reserve the step's real estate for the **MCP-introspected tools**. | ✅ shipped | batch-1 Change 2 — backend `GET /capabilities?q=` (`$or` regex over id+title); `useCapabilitySearch` (enabled on non-empty term) + `ReuseSearchDialog`; eager `useCapabilities()` removed from the step |

**Batch 1 shipped 2026-07-21** (registry +1, webui +2, tsc clean; onboarding guide §4 Steps 2–3 updated). No
ADR — UX refinements on existing semantics.

**Notes / decisions**
- The eager load is `useCapabilities()` → `listCapabilities({})` in `queries.ts`; `GET /capabilities` already
  supports `status`/`kind`/`limit`/`offset` — batch-1 adds a free-text `q` and a search-dialog picker.
- The inferred candidate chips (item 3) stay — they're hints, not the reuse browser.

## Batch 2 — 2026-07-21

| # | Step | Feedback | Status | Addressed by |
|---|---|---|---|---|
| 5 | Bindings | Executor/role/HITL are inferred from lanes, but the **Capability** dropdown is empty on every agent task. Pre-select the capability per task (from the staged/reused set, matched to the inferred candidate) so the operator changes only disagreements. | 🔧 queued | `claude_code_prompt_onboarding_ux_batch2.md` · Change 2 (+ backend: carry `suggested_capability_id` into `InferredBinding`) |
| 6 | Bindings | Side-effectful task (ApplyRepair) shows HITL `none` — misleading. Pre-selecting the capability triggers the existing floor bump → `approve_actions` shows immediately. | 🔧 queued | batch-2 (falls out of Change 2) |
| 7 | Bindings | Human-task **role** inconsistency: executor role `role.payment.ops_approver` vs HITL role `role.payment**s**.ops_approver` (singular/plural domain). Default `hitl_role` to the inferred lane role. | 🔧 queued | batch-2 · Change 3 |

**Feasibility note.** Bindings are *already* half-inferred (executor/role/HITL from lanes, via `InferredBinding`
+ the "from lane" chips). The missing half is the **capability** — which the BPMN alone can't name, but the
wizard already computes a `suggested_capability_id` per task (`capability_candidates`); batch-2 carries that into
the binding and pre-selects the matching staged/reused capability. Always overridable; the side-effect floor
still governs.

## Batch 3 — 2026-07-21 · bug: assemble returns a raw 500 on an unbound capability

| # | Step | Feedback | Status | Addressed by |
|---|---|---|---|---|
| 8 | Review & activate | Validating the pack returned a **500 Internal Server Error** (toast), not a usable message. Registry traceback: `assemble → _compose → ProcessPackManifest.model_validate → VersionedRef.parse → TypeError: VersionedRef must be a string, got NoneType`. | 🔧 queued | `claude_code_prompt_onboarding_ux_batch3.md` |

**Root cause (confirmed by code read).** A **capability** binding was saved with `capability_ref = None` — a
capability/`businessRuleTask` element left `Select…` (batch-2 pre-fill found no confident match, or the decision
task was never authored so no staged capability existed to pre-select; the `Assess` businessRuleTask is the
likely culprit in the wire-repair pack). Two gaps let that `None` reach manifest validation as a raw 500:

- `set_bindings` (onboarding.py ~408) gates the capability IO/policy check on truthiness
  (`if b.executor_type == "capability" and b.capability_ref:`) — so a `None` ref adds **no error** and is saved.
  The bijection check only catches elements with *no binding row*; here the row exists with an empty capability.
  (Contrast: `message`/`call` executors already require their ref.)
- `_compose` (~1005) then builds `{"type": "capability", "capability": None}` → `CapabilityRef.parse(None)` →
  `TypeError` → uncaught 500. Same shape for a **human** executor with `role = None`.

**Fix (batch 3).** (1) `set_bindings` requires `capability_ref` for a capability executor (and `role` for a
human executor), emitting the normal field-level **422 `bindings_invalid`** naming the element — mirroring the
existing message/call guards, surfaced inline at the Bindings step where the operator can fix it. (2) A
defensive guard in `_compose` (covering both `assemble` and `commit`) so any residual missing ref yields a clean
422, never a raw `TypeError`/500 — protecting already-saved stuck sessions too. No ADR (bug fix + guard on
existing semantics); guide §4 Step 4 gains a line that an unselected capability / unauthored decision is a hard,
element-named validation error rather than a server error.

*(Add further batches below as testing continues — Triage, Policies, Review & activate.)*
