# ADR-047 D2 — Elaboration: re-home in-code capabilities onto MCP, re-onboard seeds as data

**Status:** SHIPPED — agent-runtime image is domain-free and process-registry is green on the MCP-backed seeds
(both suites pass; option A taken for the deep_agent tool whitelist). Neutrality invariant now locked by a
cross-service fresh-domain test + a registry-validity gate over every seed pack. See the 2026-07-26 notes.
(elaborates ADR-047 **D2**)
**Date:** 2026-07-21

**Progress (2026-07-24):**
- **Step 0 — regression net:** golden outcome/artifact/HITL signatures captured per wire pack × branch
  (`agent-runtime/tests/test_d2_golden_baseline.py` + committed `golden/d2_seed_outcomes.json`).
- **In-process MCP harness (the Steps-2/3 unblocker):** the executor now brokers `mcp` caps through an
  injected client (winning over the simulation fallback); `InProcessMcpClient` dispatches `tools/call` to
  in-process tool callables, so an MCP-backed pack runs end-to-end in the non-e2e suite (domain-neutral —
  the platform carries no tool). Tested (`tests/test_inprocess_mcp_client.py`).
- **D2.1 (Step 1) — MCP server tools:** the `wire_transfer_exception` server already exposed the 10
  skill-capability tools; added the 3 **deep-agent worker tools** (`search_payment_history`, `name_match`,
  `fetch_attachment`, ported verbatim from the ex-in-code `_STUB_WORKER_TOOLS`). 13 compliant tools.
- **D2.2 template PROVEN (wire-repair-standard):** the pack re-onboarded as MCP-backed data
  (`tests/fixtures/wire-repair-standard-mcp/`) reproduces the committed golden **exactly across all four
  branches** (`tests/test_d2_rehome_equivalence.py`). The five `skill` caps became `mcp` (server-backed,
  tool-whitelisted, `input_map` authored); the three output-producers carry **per-tool output artifact
  schemas** (the binding output shape must equal the tool's output — the runtime validates it); `llm` caps
  stay (simulation for now). Server `assess_beneficiary` reason-code mapping reconciled to the seed's original
  (AC01/AC04/RC01→repairable). The harness wires an `InProcessMcpClient` to the server's **own** tool handlers
  (single source, via `tests/_mcp_server_tools.py`) — no tool logic duplicated.
- **Platform fix uncovered:** `_execute_mcp_real` now handles a **zero-output** side-effectful action tool
  (apply/notify/execute_return acknowledge but bind no artifact) instead of assuming `outputs[0]`.
- **D2.2 second pack PROVEN (wire-repair-screening):** re-homed (`tests/fixtures/wire-repair-screening-mcp/`)
  and golden-equivalent across all four branches — including the distinct `End_Hit`/`End_Clean` split. This
  pack exercised two extras: a **multi-instance** screen task and a native **reduce**. The screen tool's
  output shape (`SCREEN_OUTPUT`) replaced the old `party_result`, and the reduce's `item_path` was reconciled
  `verdict`→`status` (the server field) — data-only changes.
- **Platform fix uncovered (multi-instance × input_map):** the MI execution path (`multi_instance.py`) now
  honors ADR-048 `input_map` — an MI'd MCP capability gets its authored composite tool arguments (e.g. the
  creditor as `party`), mirroring the single-instance path. Previously MI ignored `input_map`.
- **D2.2 third pack PROVEN (wire-repair-dmn):** re-homed (`tests/fixtures/wire-repair-dmn-mcp/`) and
  golden-equivalent. `enrich` skill→mcp; the native **DMN decision table was re-authored as data** — the
  in-code enrich fabricated `gpi_status`/`payment_snapshot` that the table keyed on, absent from the server
  enrich output, so the table now routes on `dossier.payment.amount` (server default 125000 < 1M → `auto_repair`
  → the golden `End_Auto`). No platform change needed.
- **Equivalence coverage:** 3 packs × 4 branches = 12 tests green (`test_d2_rehome_equivalence.py`), spanning
  gateway-on-verdict, action tools, multi-instance, native reduce, and native DMN.
- **Fake `llm`/`deep_agent` path DONE (`SIM_CAPABILITIES`-free):** `stub_inference.py` generates a minimal
  **schema-valid** artifact straight from the pinned output schema — a domain-neutral fake wired into the
  executor (`InProcessExecutor(stub_inference=True, deep_agent_runner=SchemaStubDeepAgentRunner())`). The three
  proven packs now run with **NO `SIM_CAPABILITIES`**: mcp→client, llm→schema-stub, deep_agent→stub runner,
  decision/reduce→native. This is the Step-3 deletion prerequisite. Unit-tested (`test_stub_inference.py`).
- **D2.2 fourth pack DONE (wire-repair-agentic, the deep_agent pack):** re-homed
  (`tests/fixtures/wire-repair-agentic-mcp/`). Its skill-backed golden was a **native failure** (deep_agent is
  nemoclaw-only); with the stub runner it now **completes to `End_Resolved`** on all branches — the intended
  fix. Locked against a re-captured golden (`golden/d2_agentic_rehomed.json`); the test also asserts the old
  baseline was `failed` and the re-home flips it to `completed`.
- **Equivalence coverage:** 4 wire packs, 16 tests green — the whole capability surface (skill→mcp, action
  tools, multi-instance, native reduce, native DMN, llm-stub, deep_agent-stub).
- **Stage A DONE — structural packs migrated (nothing deleted yet):** the compose-*/scope/event/payment
  construct tests (`test_call_activity`, `test_compensation`, `test_scope_boundary`, `test_event_subprocess`)
  now run via a **`skill_impls` double** — a new `InProcessExecutor(skill_impls=…)` injection — with the tiny
  structural skills **copied to the fixture layer** (`tests/_structural_tools.py`, verbatim, so it survives
  the deletion). `app/capabilities/composition.py` + `payment_comp.py` now have **no static importers** and are
  reached by nothing at runtime → Stage-B-deletable. Full agent-runtime suite green with the in-code layer
  still present. `test_call_activity`'s exact accumulated-value assertions (`{n:11}`, `caller/leaf/final`) hold
  through the doubles, so the wiring is still proven.
- **Stage B IN PROGRESS — surfaced a behavioral-semantics gap (needs a decision):**
  - Done: the 4 wire seeds are **flipped in place** to the MCP-backed manifests; `tests/_stub_stack.py` +
    the mechanical `InProcessExecutor()`→`stub_executor()` swap migrated the bulk of the wire seed-driven
    tests (~15 files) onto the stub stack; seed-count assertions updated. The golden net was re-captured from
    the flipped seeds (agentic now completes).
  - **Blocker — 27 remaining failures, all one class:** the MCP re-home *changed two behaviors* the golden
    net (outcome/artifact-set/HITL-mode) didn't cover, and ~11 tests assert the skill-era behavior:
    1. **`approve_actions` propose-mode `proposed_actions`.** The `skill` action caps returned
       `proposed_actions` in *propose* mode (what the human approves); the MCP action tools return only a
       post-hoc *acknowledgement*. `test_engine_run`/`test_hitl_flow` assert the proposals exist.
    2. **Modeled business errors.** The `skill` caps raised `CapabilityBusinessError` for modeled failures
       (screening hit / payment rejected → routed to a BPMN error boundary → `End_Returned`); the MCP server
       tools return normal results (no `isError`). `test_error_boundary`/`test_real_business_error` assert the
       boundary routing.
  - **Decision taken (port to MCP reality).** Propose-mode `proposed_actions` treated as a skill-era detail
    (the HITL gate + the tool's post-hoc ack is the MCP reality); modeled failures use the MCP
    `isError`+`error_code` path (`stub_executor(tools={...})` injects an `isError` tool). Ported & green:
    `test_engine_run`, `test_hitl_flow`, `test_error_boundary` (5), `test_dmn_decision` (the decision now reads
    the settlement amount from the trigger via `input_map`, preserving the golden `auto_repair` + the
    `manual_review` steer), `test_egress_policy` (skill-policy tests point at structural skill caps),
    `test_repositories`, and the seed-count assertions. ~20 test files migrated; **failures 40 → 14.**
  - **Last cluster (14 failures, one boundary):** the sandbox/worker/openshell execution *substrate* (ADR-020)
    — `test_capability_worker_broker`, `test_sandboxed_executor`, `test_deep_agent`, `test_real_business_error`,
    + one `test_inprocess_mcp_client`. These run the **worker/sandbox** path, whose fakes
    (`openshell/client.py` `FakeOpenShellClient._run_sim`, `deep_agent.py` `FakeDeepAgentRunner`, `core.py`'s
    sim fallback) are the **3 remaining `SIM_CAPABILITIES` importers**. De-coupling them (the sandbox fake must
    run the same stub stack — a server-tools MCP client + `stub_inference`, injected by tests, for its
    native↔sandbox transparency guarantee) *is* the deletion.
  - **Remaining:** de-couple those 3 substrate modules → grep gate clean → purely-subtractive deletion of
    `app/capabilities/*`, `SIM_CAPABILITIES`, `KNOWN_WORKER_TOOLS`, the deep_agent whitelist. Then D2 shipped.

**Progress (2026-07-26) — Stage B FINAL done; agent-runtime image is domain-free:**
- **Substrate de-coupled (pure wiring, transparency preserved).** The 3 fakes now run the **same injected
  stub stack** as the native path, not a parallel `SIM_CAPABILITIES` implementation:
  - `core.py` — removed the `SIM_CAPABILITIES` import + `_resolve_sim`; `llm` = `stub_inference`-or-real,
    `mcp` = client-required (no sim fallback; fail-closed with no client).
  - `openshell/client.py` `FakeOpenShellClient` — delegates to `execute_capability` (the spec carries the
    pinned `descriptor`), wired to the injected `mcp_client`/`deep_agent_runner`/`stub_inference`/`skill_impls`.
    Native↔sandbox transparency is now **by construction** (same core, same stubs).
  - `deep_agent.py` `FakeDeepAgentRunner` — emits a schema-valid stub via `stub_from_schema` (was the SIM
    lookup); removed the P1-leftover `_STUB_WORKER_TOOLS` in-code whitelist — deep_agent tools are MCP tools
    resolved via the client.
  - `worker_runner.run_job` — accepts the same injectables + threads `mcp_arguments`; `broker.spec_to_job`
    serializes `mcp_arguments` so the worker makes the **same** MCP tool call as native.
- **Transparency regression found & fixed (pure wiring).** The de-coupled fake hard-coded
  `provider="openshell-fake"`, hiding the real routed provider. `_execute_llm_real` now returns structured
  `provider`/`model`; the fake forwards them (falling back to the substrate name only for kinds that don't
  route to a provider). `test_nemoclaw_fake_mode_routes_to_nemoclaw` (asserts the sandbox reports `nemoclaw`)
  is green again — the guarantee is preserved, not eroded.
- **5 substrate test files ported** onto the stub stack (`stub_executor` / `stub_fake_client` / `stub_run_job`
  helpers in `tests/_stub_stack.py`); domain imports of `app.capabilities.wire_repair` removed from
  `test_real_business_error`, `test_nemoclaw_provider_routing`, `test_capability_worker_broker`.
- **HARD GATE met:** full agent-runtime suite green (259 passed / 2 skipped) **with `app/capabilities/*` still
  present** — excluding only the live docker-stack e2e (`test_ac01_end_to_end_completes`, infra ReadTimeout).
- **Grep gate clean → purely-subtractive deletion:** removed `app/capabilities/` in full
  (`wire_repair/*` + `composition.py` + `payment_comp.py` + `screening.py`), i.e. `SIM_CAPABILITIES` and the
  deep_agent worker-tool whitelist. Full suite **re-run green** after deletion — nothing depended on it.
- **Extra domain leak removed:** `StubMcpClient` + `_screen_party_result` + `_SANCTION_MARKER` (a wire-domain
  screening stub baked into `mcp_client.py`, dead in prod — `build_mcp_client` returns `HttpMcpClient`) deleted;
  its 4 test usages ported to `InProcessMcpClient` with a steered `isError` tool. Residual domain terms in
  `app/` are now only illustrative comment/docstring examples — no import, default, field-path, or reference.

**Progress (2026-07-26 cont.) — process-registry ported to the MCP-backed seeds (option A taken): DONE.**
Running the registry suite against the flipped seeds surfaced 16 failures + a schema gap; all resolved:
- **7 re-homed artifact schemas were missing `json_schema.$id`** (agent-runtime's looser loader tolerated it;
  registry onboarding rejects it). Added `$id = https://amendia.dev/schemas/artifacts/<key-path>/<version>.json`
  to each. Agent-runtime stayed green (additive field).
- **Flipped-seed bug — `binding_io_mismatch` (the dominant cascade):** in all 4 packs the first enrich/screen
  binding declared a `trigger` input, but the capability declared `inputs: []`, so the pack failed the registry
  validator and never went active (→ resolve/roles/lifecycle all cascaded red). Fixed by adding the matching
  `trigger` input to the 4 capabilities (`enrich_investigation` ×3 + screening `screen_party`); the binding
  already sources it via `input_map`. This was a genuine seed defect the agent-runtime side doesn't validate —
  the packs weren't actually registry-onboardable before this.
- **Option A (chosen) — the deep_agent tool whitelist is now data, not code:** emptied
  `process-registry/app/validation/deep_agent.py` `KNOWN_WORKER_TOOLS` (`set()`); added two mcp tool-capabilities
  `cap.payment.name_match` + `cap.payment.search_payment_history` to the agentic seed and its
  `requires_capabilities`, so the deep_agent's whitelisted tools resolve to registered mcp caps in the pack
  (`screen_party` already resolved via the sanctions cap). `test_deep_agent_validation` updated to register +
  require the two tool-caps. The platform now carries **no** domain tool list.
- **Test-content drift ported:** `test_reduce_validation` (old `art.screening.party_result`/`verdict` →
  `art.screening.screen_party_output`/`status`), `test_api` (schema count 8→11 for the per-tool output schemas;
  kind-mismatch test selects an llm cap explicitly since the flip removed skill caps). `test_roles`,
  `test_resolve`, `test_lifecycle`, `test_pack_validator`, `test_decision_validation` went green automatically
  once the pack validated + activated.
- **Result: process-registry 223 passed; agent-runtime 259 passed / 2 skipped** (excl. the live e2e). **D2 shipped.**

**Progress (2026-07-26 cont.) — invariant locks (both additive, no platform-code change):**
- **Fresh-domain neutrality test (the invariant lock).** A brand-new domain with zero payments overlap —
  `widget-qa` (manufacturing QA, `cap.widgetqa.*` / `art.widgetqa.*`; fixture at
  `agent-runtime/tests/fixtures/widget-qa/`, pure data, no Python) — is asserted across BOTH services:
  `process-registry/tests/test_fresh_domain_neutrality.py` onboards→validates→activates it through the real
  front door; `agent-runtime/tests/test_fresh_domain_neutrality.py` executes both gateway branches
  (inspect→certify→`End_Certified`, and defect→`End_Rejected`) on the generic compiler + stub stack, its MCP
  tools injected as fixture callables. Enforced "data, not code" guards (more robust than a git-diff):
  the fixture tree contains no `.py`, and each service's `app/` image contains zero `widgetqa` references.
- **Registry-validity gate over every seed/fixture pack (the parity-gap fix).**
  `process-registry/tests/test_seed_pack_registry_gate.py` runs the real `PackValidator` (under each pack's
  `required_profile`, the production derivation) over all 13 packs under `agent-runtime/seed`, asserting each
  is registry-valid — so "agent-runtime green" can no longer mean "registry-invalid" (the exact gap that hid
  the flipped-seed `binding_io_mismatch`). It immediately caught **2 more real defects**: `compose-leaf` and
  `compose-mid` (call-activity callees) declared an entry-task input with no producer and no `input_map` —
  fixed by declaring it trigger-sourced (`{from: trigger}`), the caller supplies it as the entry payload
  (same shape as the enrich-trigger fix). Call-activity execution stays green.
- **Result: process-registry 240 passed; agent-runtime 279 passed / 2 skipped; webui 106 passed** (excl. the
  live e2e). Deferred as agreed (cosmetic): repointing the wire packs' `trigger` inputs at
  `art.payment.wire_exception`, and relocating `amendia_contracts/wire_exception.py` (a domain contract not
  imported by any platform service) out of the shared lib.

**Progress (2026-07-26 cont.) — PRODUCTION-WIRING regression fixed (harness↔factory gap):**
- **Symptom (live):** an accepted exception created an instance that produced NO HITL task. Root cause: the
  D2 flip updated the *test harness* executor wiring (`tests/_stub_stack`) but NOT the *production* composition
  root. `factory.build_executor` → `_native()` built `InProcessExecutor()` with `mcp_client=None`; post-D2 an
  `mcp` capability fails closed, so `Task_EnrichPayment` (first node, now `kind: mcp`) raised
  `CapabilityError: requires an MCP client` → instance failed before any gate → empty inbox. Every suite stayed
  green because they all inject the stack and none exercised `build_executor`.
- **Fix (3 links):** (1) `factory._capability_stack(settings)` wires the D2 stack — `mcp_client` always
  (`build_mcp_client`), `stub_inference = SIMULATION_MODE`, `deep_agent_runner` (schema-stub under simulation) —
  applied in BOTH `_native()` and `build_openshell_client` (the fake delegates to the same core); stale
  `InProcessExecutor` docstring corrected. (2) Repointed all 16 wire-pack `mcp` endpoints
  `http://stub-mcp:8056/mcp` → the deployed `http://wirefix-mcp:8060/mcp` (`mcp_stub/deploy`); registry
  introspection is endpoint-driven (no hardcoded host). (3) `tests/test_build_executor_wiring.py` drives a wire
  pack + widget-qa through the REAL `build_executor` (swapping only the MCP transport for in-process),
  asserting the wire pack reaches its first HITL gate and the fresh domain runs to `End_Certified` — the
  coverage every green suite skipped. **Verified the test catches the bug:** against the pre-fix factory it
  fails with the exact live error on `Task_EnrichPayment`.
- **Result: agent-runtime 281 passed / 2 skipped (code suite); process-registry 241 passed.** The live-stack
  e2e will pass after redeploy (rebuild agent-runtime image + re-onboard seeds with the new endpoints — seeds
  are immutable-once-active, so `down -v` or a version bump is required; the stub MCP server must be reachable
  at `wirefix-mcp:8060` on the shared network).

**Progress (2026-07-26 cont.) — MCP transport fix (surfaced after redeploy):** with the factory + endpoints
fixed, the live runtime reached `wirefix-mcp:8060` but `Task_EnrichPayment` still failed —
`MCP call failed: 307 Temporary Redirect for .../mcp` (→ `/mcp/`). `HttpMcpClient` was a naive httpx POST
missing two MCP streamable-HTTP essentials the SDK-based registry introspector already had: (1) it didn't
**follow redirects** (`/mcp`→`/mcp/` 307), and (2) it advertised only `application/json` in Accept, but the
`StreamableHTTPSessionManager` requires **both** `application/json` and `text/event-stream` (406 otherwise).
Fix: `httpx.AsyncClient(follow_redirects=True)` + dual Accept + a `_parse_mcp_http_body` helper that accepts
either a JSON or an SSE-framed reply (the server runs `stateless=True, json_response=True`, so no session
handshake is needed). **Verified end-to-end against the real FastMCP server** (ran it locally; `screen_party`
and `enrich_investigation` return their structured artifacts). Regression tests added
(`test_real_business_error`: asserts follow_redirects + dual Accept, and SSE-frame parsing).
**agent-runtime 283 passed / 2 skipped.** This fix is **code-only** — no re-onboard needed (the resolved caps
already carry the correct endpoint); just rebuild the agent-runtime image.

**Progress (2026-07-26 cont.) — one MCP client for the platform (consolidated on the SDK):** the two transport
fixes above were band-aids on a hand-rolled client. Root inconsistency: the onboarding introspector used the
official `mcp` SDK while the runtime hand-rolled httpx — so a server that introspected cleanly failed at
execution. Consolidated: added `mcp>=1.9` to agent-runtime and reimplemented `HttpMcpClient.call_tool` on the
SDK (`streamablehttp_client`/`sse_client` + `ClientSession.initialize()` + `call_tool`), the SAME connection
setup as the introspector — the SDK owns redirects/SSE/negotiation. Deleted the hand-rolled `_parse_mcp_http_body`
+ manual 307/Accept handling. ADR-035 preserved via `_result_to_artifact` (isError+error_code →
`CapabilityBusinessError`; transport/protocol → technical `RuntimeError`). New `test_http_mcp_client_integration.py`
runs the real wire-transfer FastMCP server in-process and drives the client over the full transport; 5
`_result_to_artifact` unit tests cover the ADR-035 mapping. **agent-runtime 287 passed / 2 skipped**; verified
end-to-end against the real server. See the completion report §5.

**Progress (2026-07-26 cont.) — data-contract drift reconciled (empty agent drafts): DONE.** The re-home
swapped skill→mcp but left several consumer schemas on the pre-D2 field contract the old in-code skills
fabricated: data flowed into fields the MCP tools don't emit, so schema-driven human forms rendered EMPTY
(confirmed live: `Task_ObtainInfo` showed empty `payment_snapshot`/`gpi_status`/…). Golden-equivalence missed
it — it asserts outcome + artifact-NAME set, not field content. This was seed/fixture reconciliation only, no
platform-code change.
- **Drift found (3 shared-name chains, consumer declared ≠ producer emits):**
  1. `dossier`: producer `art.payment.enrich_investigation_output` `{exception_id,payment,parties,history}`
     vs consumer-declared `art.payment.investigation_dossier` `{payment_snapshot,gpi_status,account_history,
     attachment_summaries}` — consumers: `Task_AssessRepairability`, `Task_ObtainInfo`, `Task_DraftRepair`,
     `Task_DraftReturn` (standard + agentic).
  2. `beneficiary` (standard only): producer `art.payment.assess_beneficiary_output` vs consumer-declared
     `art.payment.repair_verdict` — consumers `Task_DraftRepair`, `Task_DraftReturn`.
  3. `screening`: producer `art.compliance.screen_party_output` `{status,…}` vs consumer-declared
     `art.compliance.screening_result` `{verdict,…}` — consumers `Task_ApplyRepair`, `Task_RecordResolution`.
- **How reconciled:** repointed every drifted consumer (manifest binding **and** cap descriptor input) to the
  **producer's real output schema** — the MCP tool's actual shape. The MCP action consumers read no dossier/
  screening fields (they acknowledge); the draft_* consumers are `llm` (they receive the whole typed input);
  the forms are schema-driven, so repointing the declared input fixes the render. No prompt/form files exist
  (LLM framing is descriptor-sourced), so nothing else to change. `gateway_variables` already pointed at the
  real producer schemas.
- **Retired orphan schemas** (no producer after reconciliation): `art.payment.investigation_dossier` (standard,
  agentic, dmn), `art.compliance.screening_result` (standard, agentic), `art.payment.repair_verdict` (standard
  only — still produced by the deep_agent in agentic, kept there). Standard artifact-schemas 11→8.
- **No field fabricated in the platform.** Every consumer field now has a producer; no stub-tool output needed
  a deliberate addition for the demo path (the enrich tool already emits `payment`/`parties`/`history`).
- **"Green means populated" (Step 3):** `tests/test_content_reconciliation.py` asserts the produced dossier
  VALIDATES against `Task_ObtainInfo`'s declared form schema and carries the envelope's creditor/payment — and
  a structural guard that no consumer input schema differs from its producer's output. Verified it **fails on
  the pre-reconciliation schema** (`payment_snapshot/gpi_status required; payment/parties/history unexpected`)
  and passes after. Test-content drift from the retired schemas was ported (seed counts 11→8; refs repointed to
  `assess_beneficiary_output`/`enrich_investigation_output`). **agent-runtime 289 passed / 2 skipped;
  process-registry 241 passed.**

**Relates:** ADR-047 (domain-neutrality; D2 = "the runtime carries no per-process capability code"), ADR-048
(capability `input_map`), ADR-024 (self-descriptive descriptors), the MCP Implementor Guideline, the MCP-backed
onboarding runbook (D2's end-to-end proof).

## Where we are

P0 (config defaults), P1 (descriptor-driven executor framing), and D1 (generic trigger artifact — the
`WireExceptionEnvelope` engine import is gone) have landed. The **last** domain code in the platform image is the
in-process capability logic under `agent-runtime/app/capabilities/*` — the seed's `skill` implementations
(`wire_repair/enrich.py`, `assess.py`, `apply_repair.py`, `execute_return.py`, `notify.py`, `draft_rfi.py`,
`screening.py`, `payment_comp.py`, `composition.py`, …), the `deep_agent` in-code tools (`search_payment_history`,
`name_match`, …), and the engine's `SIM_CAPABILITIES` / `KNOWN_WORKER_TOOLS` registries that wire them in.

## Decision (concrete plan)

D2 is realised not as a code-deletion but as a **re-onboarding**: the wire capabilities move to the existing
`wire_transfer_exception` MCP server, the seed packs are re-onboarded as **MCP-backed data**, and only then is the
in-code capability layer deleted. The seed becomes exactly what any customer process is — data + an external MCP
server — with the platform assuming none of it.

- **D2.1 — one home for the capabilities.** The `wire_transfer_exception` MCP server is the single home. Ensure it
  exposes **every tool the seed packs bind**, including the ones currently implemented in-process: the `skill`
  bodies and the `deep_agent` tool functions (`search_payment_history`, `name_match`, …). Each must be
  Guideline-compliant (declared `inputSchema`/`outputSchema`, closed shapes, acknowledgement shape on side-effectful
  actions, `isError`+`error_code` for the modeled business errors the seed relies on — screening hit, payment
  rejected, needs-info).

- **D2.2 — re-onboard the seed packs as data (per-tool + `input_map`).** For each seed pack
  (`wire-repair-standard`, `-agentic`, `-dmn`, `-screening`): `skill` caps become `mcp` caps pointing at the server
  (tool-whitelisted); `llm` / `deep_agent` caps **stay** (already descriptor-driven after P1). Because MCP
  introspection yields per-tool `<tool>_input/output` artifacts that don't chain, each re-onboarded pack carries an
  **`input_map`** (ADR-048: entry→trigger, downstream→upstream output), side-effect flags on the action tools, the
  gateway variable, and schema-valid triage. These re-onboarded manifests **replace** the old skill/shared-artifact
  seed manifests and their bespoke artifact schemas as the seed data. This is the `ws-stan` pattern applied to the
  seeds — the runbook is the reference.

- **D2.3 — delete the in-code capability layer.** Remove `app/capabilities/*` (all modules), `SIM_CAPABILITIES`,
  `KNOWN_WORKER_TOOLS`, the P1 leftover hardcoded `deep_agent` tool whitelist, and every engine import of them
  (`executor/core.py`, `deep_agent.py`, `openshell/client.py`, `task_runner`, …). The runtime keeps only the
  **generic** `mcp`/`llm`/`deep_agent` executors. The L5 leftover payload-path reads (`mcp_client.py`,
  `screening.py`, `payment_comp.py`) disappear with the files.

- **D2.4 — move tests to the fixture layer, preserving coverage.** The three in-code-capability test files move to
  the MCP server's own test suite or an integration fixture. **Port** the meaningful behavioral cases (screening-hit
  business error, apply_repair acknowledgement, the deep_agent investigative path) rather than deleting them —
  losing that coverage is a regression, not a cleanup.

## Consequences

- **Positive:** the platform image is domain-free — no module imports or references a wire/payment capability. The
  seed is a fixture (an MCP server + registered data), identical in kind to any onboarded process. ADR-047's
  acceptance test holds fully.
- **Cost:** seed manifests get bigger (per-tool artifacts + `input_map` vs the old shared-artifact chaining); the
  `deep_agent` tools must be added to the stub; the engine test suite churns as `SIM_CAPABILITIES` goes.
- **This is a self-contained initiative** — it restructures the runtime image and re-onboards every seed. Do it as
  its own pass, behind a regression net (below), not bundled with anything else.

## Regression safety (required)

Before deleting anything, capture a **golden outcome** per seed pack: run a representative set of sample exceptions
(one per gateway branch — repairable / unrepairable / needs-info, plus a screening-hit) through the *current*
skill-backed packs and record the terminal outcome + produced-artifact set + HITL sequence. After D2.2/D2.3, the
MCP-backed re-onboarded packs must reproduce the **same** terminal outcomes for the same inputs. That equivalence —
not just "tests green" — is the bar that says the re-home didn't change behavior.

## Alternatives considered

- **Reshape the stub's tool schemas to emit the seed's shared artifacts** (`dossier`, `repair`, …) so the skill→mcp
  swap is a near one-line manifest change. Rejected: it edits a fixture to preserve a fixture's aesthetics and
  diverges from what real MCP introspection produces; the per-tool + `input_map` shape is the production reality and
  is already validated end-to-end.
- **Keep an in-process plugin loader for `skill` capabilities.** Deferred: valid if a future non-MCP in-process
  capability is genuinely needed, but nothing requires it today, and it would keep a code path the platform must
  maintain. Prefer MCP.

## Acceptance

1. `grep -rE "wire|repair|dossier|sanction|payment|SIM_CAPABILITIES|capabilities.wire_repair"
   backend/services/agent-runtime/app` returns only generic docstring examples — no import, registry, or reference
   to a wire/payment capability.
2. Each re-onboarded seed pack runs the golden sample exceptions to the **same** terminal outcomes as before D2.
3. A fresh-domain, fresh-MCP process still onboards, validates, activates, and executes with **zero** platform-code
   change (the standing ADR-047 test).
4. `registry`, `webui`, `agent-runtime` green (excluding the known live-stack e2e); ported capability tests pass in
   the fixture layer.
