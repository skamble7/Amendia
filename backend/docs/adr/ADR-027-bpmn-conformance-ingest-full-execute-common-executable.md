# ADR-027 — BPMN conformance strategy: ingest Full, execute Common Executable, classify-not-reject + inference

- **Status:** Accepted · **Complete** — the Common Executable program landed in full (parallel,
  timers/SLA, error boundaries, messages, sub-processes, all task kinds) and the default is now
  **`common_executable`**. See **ADR-028–033** (the construct ladder) and **ADR-034** (the finale:
  two-level collapse, default flip, end-to-end proof).
- **Date:** 2026-07-16 (completed 2026-07-17)
- **Related:** **ADR-010** (process-registry v1 — validation), **ADR-011** (native LangGraph execution — the executable subset this widens the *documentation* around), **ADR-025** (`OnboardingSession` — the wizard this enriches), **ADR-026** (dynamic roles — the inference target for lane→role); `backend/docs/amendia_bpmn_conformance_dossier.md` (the recon this is grounded in), `amendia_platform_contracts_v1.md`, `amendia_contracts_reference.md`, `libs/amendia_bpmn/*`.
- **Supersedes:** the "reject anything outside the Iteration-1 subset" posture of `libs/amendia_bpmn/parser.py` and `process-registry/app/services/onboarding.py::_parse_and_check_bpmn`.

## Context

Amendia relies on BPMN 2.0 for process onboarding, and the people who *document* the process are business users. Today the platform enforces one narrow subset — `startEvent`/`endEvent`, `serviceTask`/`userTask`, `exclusiveGateway`, conditional `sequenceFlow` — at **every** gate: the shared parser (`amendia_bpmn`), the registry validator, the runtime compiler, and (strictest) the onboarding wizard, which additionally rejects parallel and chained gateways. Anything else is a hard error and the diagram is refused (the reference wire-repair model produced 29 findings and could not be uploaded).

This conflates two separable concerns: **understanding** a diagram and **executing** it. Business users need the freedom to document the real process — lanes/personas, external-system pools, message flows, timers, boundary events, DMN decisions — and a complete diagram is a rich source Amendia can mine to *infer* pack components (roles, capabilities, artifacts, policies). None of that requires executing every construct. Full BPMN *execution* is a multi-quarter engine problem that even mature engines don't implement 100%; full BPMN *ingestion + inference* is achievable now and is where the user value is.

The BPMN 2.0 spec already gives us the vocabulary: process-modeling conformance sub-classes — *Descriptive*, *Analytic*, *Common Executable*, *Full*. We use them to split the surfaces.

## Decision

**Ingest up to *Full*; execute *Common Executable*; classify the gap honestly; let the diagram drive inference.**

### 1. Three gates, three postures

The platform stops enforcing one subset uniformly. Each gate enforces only what it must:

| Gate | Today | New posture |
|---|---|---|
| **Attach / upload** (`amendia_bpmn.parse`, onboarding `attach_bpmn`) | reject unsupported elements (hard 422) | **Classify, don't reject.** Parse full BPMN, retain every element with an executability *tier*, hard-error only on genuinely malformed input (unparseable XML, missing process, broken executable-core topology). |
| **Assemble / dry-run** (`PackValidator`, 7 stages) | 7-stage validation on the subset | Unchanged validation of the **executable core**, plus a **coverage report** (what will execute vs what is documented-only). Documented-only elements are warnings/info, never errors. |
| **Activate** (registry `validate`/`activate`) | onboarding hard-rejected parallel/chained upstream, so nothing non-runnable reached activation | **Must gain an explicit executable-compilability check** — see the correction below. The registry, not the runtime, is the activation gate; it must refuse a pack whose executable core the runtime cannot compile, as an **error**. |
| **Execute** (runtime `compile_graph`, at load) | compile the subset or `CompilerError` | **Unchanged in Phase 0–2 until execution grows.** Still the last line of defense, but it runs at *pack load*, not activation — so it must not be the *only* gate. |

Consequence, stated plainly for operators: you can document the whole process and move through onboarding; the coverage report tells you which parts execute today; constructs on the live path that aren't executable yet block *activation* (not documentation).

### 1a. Correction (discovered in Phase 0 implementation) — the activation gate is registry-side, not the compiler

The original draft of this ADR said "the compiler blocks activation." **That is false in this architecture:** `compile_graph` lives in agent-runtime and runs at **pack load**, while activation is a **process-registry** action that never invokes it. Before Phase 0, onboarding hard-rejected parallel/chained gateways, so a non-runnable pack could never reach activation. Phase 0 demoted those to warnings — which correctly makes *documentation* permissive, but **opened a gap**: a pack using `parallelGateway` / chained gateways / a multi-outgoing task can now attach → assemble → **activate**, then fail at runtime the first time a real exception is dispatched to it (the "fails at 2 a.m." anti-pattern onboarding exists to prevent).

The fix — **an explicit executable-compilability validation the registry runs at `validate`/`activate`**, surfaced as **error**-severity findings — is required to keep the "activate" gate honest. It reuses the runtime compiler's *structural* rejections (parallel gateway present, gateway→gateway chaining, task with ≠1 outgoing flow; unbound tasks and start/end counts are already covered by Stage 2 / the parser). The cleanest form is a **shared predicate in `amendia_bpmn`** that both `compile_graph` and the registry validator call, so the two can never disagree. On-path *documented* elements are already caught (a `sequenceFlow` into one is a `bpmn_dangling_flow` error); this closes the remaining `parallelGateway`/chained/multi-outgoing hole. This is a small correctness fix (Phase 0.5, or the opening task of Phase 1) — **not** an execution-semantics change.

### 2. Classification taxonomy

Every BPMN element the parser sees is tagged with one tier:

- **`executable`** — in the runtime-executable set (today: `startEvent`, `endEvent`, `serviceTask`, `userTask`, `exclusiveGateway`, conditional `sequenceFlow`). Grows in Phase 2.
- **`documented`** — a *recognized* standard BPMN element outside the executable set (lanes, pools/participants, message flows, `sendTask`/`receiveTask`/`manualTask`/`scriptTask`/`businessRuleTask`, `callActivity`/`subProcess`, `eventBasedGateway`/`inclusiveGateway`/`complexGateway`, intermediate/boundary/timer/message/error events, `dataObject`/`dataStore`, text annotations). Accepted, retained, surfaced — **warning**, never blocks.
- **`unknown`** — not a recognized BPMN element at all (typos, vendor extensions). Retained, **info/warning**, never blocks.

The tier lives in the lib (`amendia_bpmn`): elements are **retained** on `BpmnModel`, and `Finding` gains a **severity**. The registry's existing `Severity{ERROR,WARNING,INFO}` + `ok = not has_errors` (`report.py:14-17,64-69`) already means warnings don't block activation — no new registry severity machinery is needed; the fix is the **adapter** (`bpmn.py:38-40`) that currently forces every lib finding to `ERROR`, and onboarding's `_parse_and_check_bpmn`, which 422s on any finding.

### 3. Phase breakdown

- **Phase 0 — reject → classify (accept full BPMN, execute the same subset).** Lib retains unknown/documented elements + adds `Finding.severity`; the registry adapter and onboarding demote documented-only elements to warnings; the runtime rejects only on **error-severity** findings; a coverage report is produced and shown as an overlay on the existing `bpmn-js` viewer. **Non-goals:** no inference, no compiler/execution change. Unblocks business users immediately, minimal risk. (Prompt: `claude_code_prompt_phase0_bpmn_classify.md`.)
- **Phase 1 — full-BPMN importer + inference.** Deepen the retained model into real topology (edges, conditions, lanes, pools, message flows, events, boundary attachments, DMN linkage, data objects) and add an inference pass that pre-fills the `OnboardingSession` staged models: **lanes → roles**, **pools/message-flows → MCP capability + artifact candidates**, **task type → executor/HITL**, **timer/boundary events → SLA/escalation policy hints**, **`businessRuleTask`/DMN → decision capability**, **data objects → artifact seeds**, **gateway conditions → `gateway_variables`**. Inference emits the same permissive staged models the operator then confirms/edits; the committed manifest stays authoritative. **Non-goals:** execution change.
- **Phase 2 — grow execution toward Common Executable (spike first).** A time-boxed spike decides **extend-native vs embed-SpiffWorkflow**, judged on the two costs the dossier isolates (below), then implements the chosen path incrementally (parallel gateway → event-based gateway/timers → boundary events → sub-process).

### 4. Phase 2 spike — the real commit criterion

Per the dossier, the fork is **not** gateway syntax. It is:

1. **Concurrent-HITL representability.** The engine assumes exactly one interrupt per segment (`engine.py:217`) and one `WAITING_HITL` per instance (`engine.py:264-267`); two human gates on parallel branches are unrepresentable today. Extend-native means adopting LangGraph `Send` (available at 0.4.6, unused), concurrent-write reducers, and a redesigned instance/HitlTask model.
2. **Audit/checkpoint re-homing.** The LangGraph Mongo checkpoint *is* the audit record and the crash-recovery substrate (`state.py:5`, `engine.py:194-204`). Embed-Spiff inherits parallel/boundary/events natively but requires re-homing durable state + memo keying (`memo.py:47`) onto Spiff's task tree and reconciling two audit models.

The spike must answer these two, plus the product question **"does the roadmap require concurrent *human* gates, or is sequentializing the fan-out acceptable?"** — not "which gateways are covered."

**Decisions locked (post-Phase-1):**
- **Sequentializing the fan-out is acceptable** — the platform does *not* need two human gates open simultaneously on parallel branches. This removes concurrent-HITL representability as a hard blocker (the one-`WAITING_HITL`-per-instance model can stay; when multiple branches interrupt in a superstep, they are surfaced **one at a time**). This **favors extend-native** over embed-Spiff, so Phase 2 is framed as *extend the native engine, validated by a focused spike on the riskiest construct* (parallel gateway with serialized human gates), not a 50/50 bake-off. Embed-Spiff remains the fallback only if the spike hits a hard blocker.
- Note the tailwind: `ProcessState` already declares **concurrent-safe reducers** — `artifacts` dict-merge and `actor_log` append (`state.py:23-24`) — so parallel-branch writes merge without new channel design. The real work is the compiler (emit `Send` fan-out + a join) and sequentializing multiple pending interrupts, not the state model.

### 5. Resolved decisions (the dossier's Final-synthesis §4)

1. **Enriched `BpmnModel`/`BpmnInventory` shape** — designed in **Phase 1**, not Phase 0. Phase 0 retains only `{id, kind, tier}` per element (enough for coverage); Phase 1 adds the full topology inference needs.
2. **Classification taxonomy** — `executable | documented | unknown`, carried as a per-element tag on `BpmnModel` **and** `Finding.severity` in the lib; the registry maps to `Severity`; the webui overlay derives from it.
3. **Native-default memoization** — **DECIDED: flip on-by-default in native mode**, done as **Phase 2.0** (opening hardening), so a resumed HITL node commits the *reviewed* artifact rather than a re-invoked one. Latent replay hazard today; parallelism would amplify it. Config keeps an explicit off switch.
4. **Build-vs-buy** — **DECIDED (given §4 "sequentialize acceptable"): extend-native**, validated by the Phase 2.1 spike on parallel gateways + serialized human gates. Embed-Spiff is the fallback only if the spike surfaces a hard blocker (checkpoint/HITL model can't hold). The spike, not a blind commit, is the go/no-go.
5. **Hand-maintained onboarding types** — the whole onboarding contract is hand-synced to `webui/src/api/services/registry.ts`, outside `gen:api:check`. Phase 0 keeps hand-sync (updating types in lockstep) and **adds a follow-up to bring onboarding under `gen:api`** so later model growth can't ship a silently-wrong UI.

**Also unified in Phase 0:** the process-`<process>` selection split — onboarding prefers `isExecutable="true"` (`onboarding.py:650-659`) while the shared parser matches exact `expected_process_id` (`parser.py:44-45`). Phase 0 makes both use one helper.

## Consequences

- Business users document the full process immediately; the platform is honest about what runs via a coverage report rather than refusing the diagram.
- The diagram becomes an inference source (Phase 1), cutting manual onboarding form-filling and capturing roles/personas/external systems the wizard otherwise can't know.
- Execution remains a bounded, spec-anchored, incrementally-fundable target (Common Executable) rather than an open-ended "implement all of BPMN" commitment.
- The `BPMN hash-pinned` + `manifest is the execution source of truth` invariants hold; the BPMN is simply allowed to be richer, and onboarding *derives* a draft from it.

## Traps recorded for maintainers

1. **Documented elements must be retained but kept out of the typed executable collections.** If a documented event is added to `tasks`/`end_events`, the compiler mis-runs it. Retain documented/unknown elements in a **separate** collection; leave the executable typed collections meaning exactly "executable." (`parallelGateway` stays in `parallel_gateways` so the compiler and the new registry compilability check both still refuse it — see §1a.)
2. **The runtime load path rejects on *any* finding code today** (`bundle.py:65`, `engine.py:125`). Once the lib emits warning-severity findings, these must filter to **error-severity only**, or every full-BPMN active pack fails to load. *(Done in Phase 0.)*
3. **On-path vs off-path documented elements.** A documented element reached by a `sequenceFlow` puts it on the live path — the parser emits a `bpmn_dangling_flow` **error** (its target isn't a known executable node), which blocks validation/activation registry-side. An off-path documented element (a lane, an unattached annotation, a boundary event) does not, and the executable core runs. This is the intended, self-enforcing boundary. Note the mechanism is the **parser's dangling-flow error surfaced through registry validation**, not the runtime compiler (which runs at load, not activation — §1a); `parallelGateway`/chained/multi-outgoing are the cases §1a's registry compilability check must add.
4. **Coverage semantics are authoritative server-side.** The webui overlay must derive from the server's classification/coverage, not a client-side bound/unbound set-diff, or it will disagree with the dry-run.