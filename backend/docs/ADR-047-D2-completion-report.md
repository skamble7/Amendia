# ADR-047 D2 — Completion Report

**Scope:** re-home in-code capabilities onto MCP, re-onboard the seeds as data, delete the domain code so the
platform image is domain-free — then get both services green on the MCP-backed seeds, lock the neutrality
invariant, and fix the production-wiring regression the flip introduced.

**Status:** SHIPPED (code green across all services). The runtime is now consolidated on the official MCP SDK
(one client for the platform). One live redeploy step remains to pick up the client change; two cosmetic
follow-ups deferred by agreement.

**Final test state:** agent-runtime **287 passed / 2 skipped** · process-registry **241 passed** · webui
**106 passed** (the 2 skips + 1 deselect are the live docker-stack e2e).

---

## 1. Substrate de-coupling & deletion — the platform image is domain-free

The three execution-substrate fakes were re-pointed to run the **same injected stub stack** as the native
path, not a parallel `SIM_CAPABILITIES` implementation:

- **`core.py`** — the single kind-dispatch. No simulation fallback: `mcp` fails closed without a client;
  `llm` is `stub_inference`-or-real; `deep_agent` uses the injected runner.
- **`openshell/client.py` `FakeOpenShellClient`** — delegates to `execute_capability` (the sandbox spec
  carries the pinned descriptor), wired to the injected `mcp_client` / `deep_agent_runner` / `stub_inference`
  / `skill_impls`. Native↔sandbox transparency is now **by construction** — same core, same stubs.
- **`deep_agent.py` `FakeDeepAgentRunner`** — emits a schema-valid stub via `stub_from_schema`; the hardcoded
  worker-tool whitelist was removed (deep_agent tools are MCP tools resolved via the client).
- **`worker_runner.run_job` / `broker.spec_to_job`** — accept the same injectables and thread `mcp_arguments`,
  so the worker makes the *same* MCP call as native.

**Transparency regression caught & fixed (pure wiring):** the de-coupled fake initially hard-coded
`provider="openshell-fake"`, hiding the real routed provider. `_execute_llm_real` now returns structured
`provider`/`model` and the fake forwards them — `test_nemoclaw_fake_mode_routes_to_nemoclaw` (asserts the
sandbox reports `nemoclaw`) is green again.

**Deletion (purely subtractive):** after a clean grep gate, `app/capabilities/*` (the SIM skills +
composition/payment/screening) was deleted and the full suite re-ran green. The dead wire-domain
`StubMcpClient` + `_screen_party_result` + `_SANCTION_MARKER` were also removed (its test usages ported to
`InProcessMcpClient` with a steered `isError` tool).

**Test harness (the D2 stub stack), all in `tests/`:** `stub_executor` / `stub_fake_client` / `stub_run_job`
wire `InProcessMcpClient(server_tool_map())` + `SchemaStubDeepAgentRunner` + `STRUCTURAL_IMPLS`. Five substrate
test files were ported onto it.

---

## 2. Process-registry port — Option A (data, not code)

Running the registry suite against the flipped seeds surfaced 16 failures + a schema gap; all resolved.

- **`KNOWN_WORKER_TOOLS` emptied** (`validation/deep_agent.py` → `set()`). The deep_agent's whitelisted tools
  now resolve to **MCP tool-capabilities in the pack**: `cap.payment.name_match` +
  `cap.payment.search_payment_history` were added to the agentic seed and its `requires_capabilities`
  (`screen_party` already resolved via the sanctions cap). The platform carries **no domain tool list**.
- **Real seed defects the validator caught (fixed, not loosened):**
  - 7 re-homed artifact schemas were missing the canonical `json_schema.$id` registry onboarding requires
    (agent-runtime's looser loader tolerated it).
  - `binding_io_mismatch` on all 4 packs: the first enrich/screen binding declared a `trigger` input but its
    capability declared `inputs: []` → the packs weren't registry-onboardable. Fixed by adding the `trigger`
    input to the 4 capabilities (the binding already sources it via `input_map`).
- **Test-content drift ported:** `test_reduce_validation` (`art.screening.party_result`/`verdict` →
  `screen_party_output`/`status`), `test_api` (schema count, kind-mismatch base cap). `test_roles`,
  `test_resolve`, `test_lifecycle`, `test_pack_validator`, `test_decision_validation` went green once the pack
  validated + activated.

---

## 3. Neutrality invariant — locked by two durable nets

- **Cross-service fresh-domain test.** A brand-new domain with zero payments overlap — `widget-qa`
  (manufacturing QA, `cap.widgetqa.*` / `art.widgetqa.*`, pure fixture data at
  `agent-runtime/tests/fixtures/widget-qa/`) — is asserted in **both** services:
  `process-registry/tests/test_fresh_domain_neutrality.py` onboards→validates→activates it;
  `agent-runtime/tests/test_fresh_domain_neutrality.py` executes **both** gateway branches
  (inspect→certify→`End_Certified`; defect→`End_Rejected`) on the generic compiler + stub stack. Enforced
  "data, not code" guards (more robust than a git-diff): the fixture has no `.py`, and each `app/` image
  carries zero `widgetqa` references.
- **Registry-validity gate over every seed pack.** `process-registry/tests/test_seed_pack_registry_gate.py`
  runs the real `PackValidator` (under each pack's `required_profile`, the production derivation) over all 13
  packs under `agent-runtime/seed`. This closes the gap that let the flipped-seed `binding_io_mismatch` hide —
  "agent-runtime green" can no longer mean "registry-invalid." It immediately caught **2 more defects**:
  `compose-leaf` / `compose-mid` (call-activity callees) declared an entry input with no producer and no
  `input_map` → fixed by declaring it trigger-sourced (the caller supplies it as the entry payload).

---

## 4. Production-wiring regression (found in the live stack)

**Symptom:** an accepted exception created an instance that produced no HITL task. The instance actually
**failed on its first node** (`Task_EnrichPayment`) — "Accepted" is an ingestion-time status, upstream of
execution, so it masked the failure.

**Root cause:** the D2 flip wired the executor stack into the **test harness** (`tests/_stub_stack`) but not
the **production composition root** (`factory.build_executor`, the path `main.py` uses). Every suite stayed
green because they all inject the stack; none drove `build_executor`. Four links:

| # | Failure | Fix |
|---|---------|-----|
| 1 | `_native()` built `InProcessExecutor(mcp_client=None)` → post-D2 `mcp` fails closed → enrich died on node 1 | `factory._capability_stack(settings)` wires `mcp_client` (always) + `stub_inference = SIMULATION_MODE` + `deep_agent_runner`, into both `_native()` and `build_openshell_client`; stale `InProcessExecutor` docstring corrected |
| 2 | Seed cap endpoints pointed at the placeholder `http://stub-mcp:8056/mcp`, not the deployed `http://wirefix-mcp:8060/mcp` | Repointed all 16 wire-pack endpoints; registry introspection is endpoint-driven (no hardcoded host) |
| 3 | No test drove `build_executor` — the exact gap | `tests/test_build_executor_wiring.py`: wire pack reaches its first HITL gate, widget-qa runs to `End_Certified`, through the real root (only the MCP transport swapped to in-process). **Proven to fail on the pre-fix factory with the exact live error.** |
| 4 | `HttpMcpClient` (naive httpx) didn't follow the `/mcp`→`/mcp/` 307, and sent only `Accept: application/json` (the session manager needs `+ text/event-stream`, else 406) | `httpx.AsyncClient(follow_redirects=True)` + dual `Accept` + `_parse_mcp_http_body` (JSON **or** SSE frame). Server runs `stateless=True, json_response=True` so no handshake needed. **Verified end-to-end against the real FastMCP server** (`screen_party`, `enrich_investigation` return structured artifacts); regression tests added. |

**Redeploy note:** fixes 1–2 needed a rebuild + re-onboard (seeds are immutable-once-active → `down -v` or a
version bump). Fix 4 is **code-only** — the resolved caps already carry the correct endpoint, so only an
agent-runtime image rebuild is required. After that the instance reaches `waiting_hitl` and a task appears.

---

## 5. One MCP client for the platform (consolidated on the SDK) — DONE

Previously two clients talked to the same server: the onboarding introspector used the official `mcp` SDK,
while the runtime used a **hand-rolled `httpx`** `HttpMcpClient`. That divergence is why a server that
introspected cleanly failed at execution (the runtime client had to be hand-patched for the 307 + Accept + SSE
that the SDK handles for free).

**Consolidated:** `mcp>=1.9` added to agent-runtime; `HttpMcpClient.call_tool` reimplemented on the SDK —
`streamablehttp_client` (or `sse_client`) + `ClientSession.initialize()` + `call_tool`, the **same connection
setup the introspector uses**. The SDK owns the transport (redirects, streamable-HTTP/SSE framing,
negotiation). Endpoint still comes from the descriptor; non-secret headers preserved.

- **ADR-035 contract preserved exactly:** a `CallToolResult` with `isError: true` + a conventional
  `error_code` → `CapabilityBusinessError` → BPMN error boundary (`_result_to_artifact`); a
  transport/protocol/handshake failure → technical `RuntimeError` (caller maps to `CapabilityError`).
- **Deleted** the hand-rolled protocol code: `_parse_mcp_http_body` (SSE/JSON body parsing, ~17 lines), the
  manual 307-follow + dual-Accept + JSON-RPC-envelope `call_tool` body (~40 lines → ~20 lines of SDK code),
  the `# [confirm]` framing caveats, and the httpx-mock test harness `_install_fake_httpx` + its 4 transport
  tests (~85 lines).
- **Tests:** 5 `_result_to_artifact` unit tests (ADR-035 mapping — business error, `MCP_TOOL_ERROR` fallback,
  structured/content-block artifact, technical), and a **real-server integration test**
  (`test_http_mcp_client_integration.py`) that spins up the actual wire-transfer FastMCP server in-process and
  drives `HttpMcpClient` over the full transport — `screen_party`/`enrich_investigation` return structured
  artifacts; a tool error is handled over the wire. This is the guard the in-process double can't give (a
  hand-rolled client passed its mocks while failing on the real wire). The `build_executor` wiring test stays
  green. **Verified end-to-end against the real FastMCP server** (screen_party → `{status: hit}`, enrich →
  dossier). **agent-runtime 287 passed / 2 skipped.**
- **Tradeoff accepted:** the SDK opens a session (one `initialize` round-trip) per call vs. the old single
  stateless POST — negligible at HITL pace; poolable per-endpoint later if it ever matters (not done —
  correctness first).

---

## 6. Cross-cutting theme

Every defect in this arc has the same shape: **the test harness and the production composition root diverged,
and nothing tested through the real root.** The transparency fake, the factory wiring, and the MCP transport
all passed their harness-injected tests while the real path was broken. The durable lesson (recorded in ADR +
project memory): **any change to the executor / capability contract must be tested through `build_executor`,
not just the injected harness** — and the runtime's real MCP client must be exercised against a real server,
not only the in-process double.

---

## 6b. Final live-only loop — the LLM-poisoned `repair_hint` (fixed)

The last live-only defect had the same divergence shape as §6, but at the *artifact-schema* layer:

- `art.payment.rfi_request` carried an **optional** `repair_hint` field. The **real** `draft_rfi` LLM
  auto-filled it `'needs_info'` — restating the problem, not resolving it. The **schema-stub** harness
  omits optional fields, so the rfi never carried it → harness terminated, **live looped**.
- The assess binding passed the whole rfi as `provided_info`, and `assess_beneficiary`'s `_dig` is
  **recursive** (top level *or one level down inside any payload object*) → it dug the nested
  `repair_hint='needs_info'` back out and re-steered **every** re-assessment. UI proof:
  `{"repair_verdict":"needs_info","rationale":"steered by repair_hint='needs_info'"}`, looping
  `Task_AssessRepairability ↔ Task_ObtainInfo` forever.
- **Fix (seed-only, no platform code):** delete `repair_hint` from `rfi_request` in both packs so the
  schema-constrained LLM cannot emit it, and drop the now-dangling `repair_hint` source from the assess
  `input_map`. The loop now flips **purely** on `provided_info` presence → info-obtained → repairable.
- **Verified against a real running server:** AC01 → `repairable` (no ObtainInfo), BE04 → `needs_info` →
  ObtainInfo → (rfi present) → `repairable`. Suites: agent-runtime 310 pass / 2 skip, process-registry 241.
- **Rule added to memory:** never pass a whole LLM-drafted artifact into a tool whose `_dig` recurses — an
  optional field the real provider fills can collide with the tool's steer keys. Keep request/RFI artifacts
  free of verdict-shaped fields.

## 6c. Needs-info exit contract — human-authored resolution (addendum §C/§D)

§6b stopped the hang but the flip was semantically hollow: it keyed off *the LLM draft rfi existing*, not off
the analyst supplying anything, and offered no human-controlled exit. The addendum's exit contract made this
precise (`Gateway_Repairable` fires the non-default flow ONLY on `repair_verdict ∈ {repairable, unrepairable}`;
any other value → default → back to Obtain-Info) and identified the real root: **Task_ObtainInfo has no
draft-RFI service task — `draft_rfi` is bound onto it as an assist, so "accept draft + comment" commits the
machine's *questions*, never a human *answer*.** The human had no channel to resolve.

**Final design (Option A — dedicated human-authored resolution artifact):**

- New `art.payment.info_resolution {outcome: resolved | cannot_obtain, details?}` as a **second output** of
  `Task_ObtainInfo` with **no assist** — the `draft_rfi` LLM structurally cannot fabricate it. (Named
  `info_resolution`, not `resolution`: `Task_RecordResolution` already emits `resolution`.)
- `assess_beneficiary` keys off `resolution.outcome` at top precedence: `resolved` → repairable → End_Resolved;
  `cannot_obtain` → unrepairable → DraftReturn → ApproveReturn → ExecuteReturn → **End_Returned** (the §D
  analyst-controlled terminal exit — no more default-only unbounded loop). `null` on the first pass (no
  Obtain-Info yet) → reason codes drive. `ASSESS_INPUT` drops `repair_hint`/`provided_info`, adds a nullable
  `resolution`; the input_map reads it via an ADR-048 optional source.

**Two domain-free platform changes** (flagged, per the seed-only-where-possible convention — a human channel
that survives resume was not expressible without them):

1. `task_runner._run_manual` — a manual-task output with no assist draft is now surfaced into the gate payload
   with empty (`{}`) data so the UI renders a blank schema-form; the existing commit loop then REQUIRES the
   human to author it via `edits` (no draft to fall back on). The platform learns nothing domain-specific.
2. `process-registry pack_validator._stage5_artifacts_io` — a `human`+assist binding's IO need only be a
   **superset** of the assist's (assist ⊆ binding; extra outputs are human-authored). Capability executors
   stay strict set-equal. Without this the pack fails `binding_io_mismatch` (assist drafts `rfi`, not
   `info_resolution`).

**Verified:** real server boots with the closed schema and honors `resolution` both directions; registry gate
green over both packs; golden regenerated (needs_info_be04 gains `info_resolution`, one loop, End_Resolved);
`test_rework_loop.py` asserts the resolved→End_Resolved and cannot_obtain→End_Returned paths on **verdict
content**, not just artifact names. Suites: agent-runtime 311 pass / 2 skip, process-registry 241 pass. The
**agentic** pack's BE04 routes straight to repairable (never enters needs-info), so it neither loops nor needs
the change — left untouched, not the live pack.

## 6d. Empty approve_actions gate for MCP action tools (D2 propose-mode regression)

Same regression class as the loop, one node further on: pre-D2 the action tasks were in-code `skill`s whose
`propose` returned the action list; the re-home to generic `mcp` capabilities dropped propose semantics.
`_execute_mcp_real` has no propose branch — it calls the tool and returns `{outputs}` in every mode — so
`_run_approve_actions` read `proposed_actions=[]`. Live, the gate opened with nothing to authorize (the frontend
"select ≥1 action" guard wedged the instance); and proposing-by-invoking would have fired the side effect
*before* approval. The golden net asserts terminal outcomes, not gate contents, so it stayed green.

- **Step 0 finding:** `Task_ApplyRepair` and `Task_NotifyParties` are structurally identical (`kind=mcp`,
  `side_effect=side_effectful`, no bound output, input_map) and an instrumented AC01 run shows **both** emit
  `count=0` proposed actions. There is no second code path — ApplyRepair clearing live while NotifyParties
  didn't was operator conditions, not structure. The one fix covers both (and `Task_ExecuteReturn`).
- **Fix (domain-free, `task_runner` only):** `_propose_actions` — a `skill` still returns its own
  side-effect-free `proposed_actions`; an `mcp`/`llm`/`deep_agent` capability that is `side_effectful`
  **synthesizes exactly one** `ProposedAction` host-side (`action_id` deterministic from pid+element+tool;
  `kind`=tool name; `summary`=descriptor `title`/`description`; `detail`=the resolved input_map arguments the
  tool will receive) and the tool is **never invoked** until `mode="execute"` after approval. A `read_only`
  capability under `approve_actions` is a pack authoring error — left empty, surfaced by the frontend.
- **Frontend (Step 3, defensive):** `AuthorizeActionsVariant` degrades an empty gate to a "no actions proposed —
  pack/config error" panel with Reject only; never auto-approves.
- **Tests (Step 4):** `test_approve_actions_synthesis.py` asserts, on the real `server_tool_map`, that each
  side-effectful action gate presents ≥1 action whose `detail` equals the args the tool receives, that the tool
  fires **exactly once and only after approval**, and that the AC06 return branch authorizes `ExecuteReturn` and
  completes. The golden net now records the action count per `approve_actions` gate (all `1`) and a new
  `unrepairable_ac06` branch — so an empty gate changes the signature and fails the net going forward.
- **Verified:** agent-runtime 313 pass / 2 skip, process-registry 241, webui 106/106 + tsc clean.

## 6e. Needs-info loop ported to wire-repair-agentic (deep_agent Assess)

`wire-repair-agentic` had the same `Gateway_Repairable →(default)→ Task_ObtainInfo → Task_AssessRepairability`
loop, unfixed. It is **not** a copy of standard: its Assess is a `deep_agent` (`cap.payment.assess_beneficiary_agentic`
→ `art.payment.repair_verdict`), so there is no MCP stub to map `resolution → verdict`. Per the design decision,
the mapping is domain and lives in the capability's prompt (prod) — never the engine.

- **Seed (Steps 1–3):** copied `art.payment.info_resolution` into the pack (+ registered, 8→9 artifacts); added
  `info_resolution` as the no-assist 2nd output of `Task_ObtainInfo` (renders as a blank form via the shipped
  `_run_manual` path); added `info_resolution` as an Assess **input** with an ADR-048 **optional** input_map
  source (absent-tolerant → null first pass, present on the loop back-edge). Because Assess is a *capability*
  executor (strict binding⇄capability IO), `info_resolution` was also declared on the capability's `inputs`
  (standard didn't need this — there resolution is a composite field under one `dossier` input).
- **Prompt (Step 4):** the mapping's home. The registered prompt is external (keyed by `prompt_key`, no in-repo
  text); the intent is recorded on the capability `description` (seed data) and must be reflected in
  `prompt.payment.assess_beneficiary_agentic`.
- **CI stub (Step 5):** the platform `SchemaStubDeepAgentRunner` emits the first enum (`repairable`) and ignores
  inputs — so agentic would never enter the loop in CI and a test would be green-but-unverified. Added
  `tests/_agentic_assess.WireAgenticDeepAgentRunner` (fixture layer, the CI analog of standard's MCP stub) that,
  for the agentic Assess capability only, **reuses the standard `assess_beneficiary` handler** (identical
  reason-code + resolution → verdict mapping) and delegates every other deep_agent to the schema stub. Wired as
  the default deep-agent runner in `tests/_stub_stack` (native/worker/sandbox stay transparent).
- **Tests (Step 6):** `test_rework_loop_agentic.py` asserts, on the shipping path, `resolved` → `repair_verdict
  repairable` → End_Resolved and `cannot_obtain` → `unrepairable` → End_Returned, each in exactly one cycle, with
  `info_resolution` committed and surviving resume — content, not just artifact presence. The D2 golden set now
  exercises agentic through the loop (BE04 enters+exits; AC06 returns) instead of the old
  first-enum-`repairable` shortcut that never looped.
- **No platform change:** the memo visit-count and the `approve_actions` synthesis already covered agentic
  (confirmed: its action gates present populated lists, count folded into the golden). Verified: agent-runtime
  315 pass / 2 skip, process-registry 241. **Every wire pack with the needs-info loop is now fixed.**

## 6f. Deep-agent system prompt is now descriptor-framed (title + description)

The agentic port (§6e) put the `resolution → verdict` mapping in the capability's **description**, but the real
deep-agent runner never sent it: `RealDeepAgentRunner` built `system_prompt` from `capability_id` + `prompt_key`
(a literal label, no resolvable text) and dropped `title`/`description` — so the rule reached the live model
through **zero channels**. The llm path (`run_real_llm`) already injects the descriptor; deep_agent didn't — a
real platform inconsistency, not just this bug. CI was green only because `WireAgenticDeepAgentRunner` bypasses
the real runner.

- **Change 1 (platform, domain-neutral):** `core._execute_deep_agent` now passes `title`/`description` to the
  runner; a new pure `deep_agent.build_system_prompt(...)` frames them into the prompt exactly like
  `run_real_llm` (`You are the '{id}' capability — {title}. {description} Task: {prompt_key}. …`). The
  `DeepAgentRunner` protocol + all four runners (Real/Fake/SchemaStub/WireAgentic) take the new args.
- **Change 2:** the agentic assess `description` rewritten as a crisp imperative RULE (present `info_resolution`
  is authoritative: `resolved`→repairable, `cannot_obtain`→unrepairable; absent/null→assess from dossier), and
  the stale "reflect this in the registered prompt" meta-note removed (it now goes to the model verbatim).
- **Change 3:** `test_deep_agent_prompt.py` asserts — with no live LLM — that the constructed prompt contains the
  descriptor's title + description, and that the real seed capability's mapping text is present in the prompt.
  This is the assertion that would have caught the gap.
- **Change 4 — live reachability (reported, not faked):** in **both** the docker-compose dev stack and the default
  Helm deploy, `AGENTRT_DEEPAGENT_REAL=false` → the factory wires `FakeDeepAgentRunner` (schema stub → first enum
  `repairable`, ignoring the description AND the resolution input) even in `native`/non-simulation. So **today the
  agentic Assess does not run the real model at all**: this fix takes effect only when `DEEPAGENT_REAL=true`,
  which additionally needs the `deepagents` SDK (OpenShell-sandbox-only) and a reachable inference endpoint (dev
  is the `stub-inference:8055/v1` stub, not a real NIM; prod `inference.local/v1`). **Consequence:** a live
  agentic needs-info run that exercises the real model — and thus the DoD item "live agentic run terminates both
  branches" — is **blocked on provisioning the nemoclaw/NIM harness**, not on this code. Until then agentic Assess
  live uses the fake stub (always `repairable`), which neither reproduces the loop nor honors the instruction.
- **Verified:** agent-runtime 318 pass / 2 skip. The fix is correct and unit-verified; live confirmation awaits
  the real deep-agent harness.

## 7. Open items

- **Done:** runtime consolidated on the MCP SDK (§5) — one client for the platform.
- **Deferred (cosmetic, by agreement):** repoint the wire packs' `trigger` inputs at the declared
  `art.payment.wire_exception`; relocate `amendia_contracts/wire_exception.py` (a domain contract not imported
  by any platform service) out of the shared lib.
- **Optional (not done — correctness first):** pool/reuse an SDK session per endpoint if the per-call
  `initialize` round-trip ever matters.
- **Live:** rebuild the agent-runtime image to pick up the transport + SDK-client changes, then re-run the
  exception and confirm the task reaches the inbox.

Nothing is committed — all changes are staged in the working tree and recorded in
`backend/docs/adr/ADR-047-D2-elaboration-runtime-capability-decoupling.md`.
