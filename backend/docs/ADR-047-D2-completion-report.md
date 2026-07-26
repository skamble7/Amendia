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
