# ADR-021 — The `deep_agent` capability kind (bounded agent loop inside one node)

- **Status:** Accepted
- **Date:** 2026-07-10
- **Related:** the design doc `amendia_secure_runtime_nemoclaw_plan.md` §9 (two planes of autonomy — the
  spec for this phase), ADR-020 (the worker / shared core / broker seam this extends), ADR-019
  (memoization + contract-derived egress), ADR-018 (the `nemoclaw` managed-inference provider — the
  intended model), ADR-017 trap 7 (orchestration stays deterministic), `amendia_platform_contracts_v1.md`
  §2/§4 (capability descriptor, runtime union, HITL matrix) + the registry validation matrix.
- **Advances:** adds a fourth capability `kind: "deep_agent"` — a bounded LangChain Deep Agents loop
  that runs **inside one node** to emit a schema-valid artifact, `nemoclaw`-only, HITL-gated, memoized.

## Context — two planes of autonomy (design §9)

- **Orchestration plane** (BPMN → compiled LangGraph) stays **deterministic, non-negotiable**. The BPMN
  is the plan; it is never handed to an agent. Bijection, gateway routing, SoD, pinned versions, and the
  checkpoint audit trail depend on it (ADR-017 trap 7).
- **Execution plane** (inside one node) is where a bounded agent loop legitimately fits. A `deep_agent`
  capability's *internal* work can be open-ended, but it is **caged by the contract**: pinned input/
  output artifact schemas, an egress + tool whitelist, a step budget, a **required HITL gate**, and
  **mandatory memoization**. The contract boundary — not the (now emergent) code — is the guarantee.

## Decision

### Part A — contract extension + registry validation (additive)

`CapabilityKind.DEEP_AGENT` + a `DeepAgentRuntime` runtime-union variant (`prompt_key`,
`model_config_key`, `tools` whitelist, `structured_output`, `budget{max_steps,max_tokens}`). Additive:
every existing descriptor/pack is unaffected (new descriptor ⇒ re-onboarding, ADR-016 trap 3 — expected).
An optional `ProcessPackManifest.deep_agent_justifications` map carries the escape hatch for a
side-effectful loop.

The registry validator (`validation/deep_agent.py`, stage 4) adds four deterministic rules for every
binding resolving to a `deep_agent` capability:
1. **`deep_agent_requires_hitl`** — must be bound behind a HITL gate (never `none`).
2. **`deep_agent_side_effect_not_justified`** — `read_only` unless the pack provides a
   `deep_agent_justifications[capability_id]` (a side-effectful autonomous loop is refused by default).
3. **`deep_agent_tool_unresolved`** — every `tools[]` entry resolves to a known worker function or a
   registered MCP tool in the pack.
4. **`deep_agent_pack_requires_nemoclaw_mode`** (warning) — the pack may only activate/run where
   `nemoclaw` mode is available (ADR-017 §4.3); the hard fail-closed is at runtime (Part D).

### Part B — `DeepAgentRunner` (interface + fake + real), wired into the shared core

`DeepAgentRunner` protocol: `{prompt, input_artifacts, tools, output_schema, model_ref, budget}` → a
structured artifact the **host** validates. Runs inside the worker/sandbox.
- **`FakeDeepAgentRunner`** — deterministic, the **CI/dev default**. Produces a schema-valid artifact
  (the pilot: a `repair_verdict` with `evidence[]`) via the paired simulation capability — no model/loop.
- **`RealDeepAgentRunner`** — invokes the actual harness, integration-gated. Built against the
  **confirmed** SDK surface only: `create_deep_agent(model=, tools=, system_prompt=)` + `agent.ainvoke(
  {"messages":[…]}, config={"recursion_limit": budget})` (standard LangGraph bound). The
  **structured-output param** and **MCP-tool passing** are **not documented** → `# [confirm]`, handled by
  prompt-instruction + host-side schema validation (the §9.2 caging model) rather than an invented SDK
  surface. Model calls go to `inference.local/v1` (ADR-018/020).

Wired into `executor/core.py` kind-dispatch (`deep_agent_runner` param, mirroring `mcp_client`). The
worker builds the runner (`build_deep_agent_runner`); the fake OpenShell client runs the pilot via its
registered simulation. The host still `_validate`s against the pinned schema, commits, checkpoints, and
appends `actor_log` with the trace id (ADR-017 trap 2).

### Part C — egress + tool policy from contract

`derive_egress_policy` (ADR-019) handles `deep_agent`: egress = the managed inference proxy host
(`inference.local`); `agent_tools` = `runtime.tools` — the **only** tools a (possibly injected) loop may
call. **Injection resistance (§9.6):** a `deep_agent` reads *untrusted* attachments/correspondence; the
egress allowlist + tool whitelist mean even a fully hijacked loop reaches only what the contract granted —
a reason *for* the sandbox, not merely a risk of it.

### Part D — mandatory memoization + nemoclaw-only/HITL fail-closed

`deep_agent` output is non-deterministic, so **memoization is mandatory** (independent of
`AGENTRT_MEMOIZE_CAPABILITIES`): the `SandboxedExecutor` forces the memo on for `deep_agent` and **fails
closed** if no memo store is wired. On a `review_after` resume the memoized (reviewed) artifact commits
and the harness is **not** re-run; `edit_and_approve` / `reject→re-run` correctness carries over from
ADR-019 (attempt-keyed). Runtime enforcement (belt-and-suspenders with the registry): the shared core
**refuses `deep_agent` when no runner is present** (native/in-process → fail closed, nemoclaw-only), and
the task runner refuses an un-gated `deep_agent` node.

### Part E — pilot capability + pack (non-destructive)

`cap.payment.assess_beneficiary_agentic` (read-only investigation → `art.payment.repair_verdict` with
`evidence[]`) + a new pack `wire-repair-agentic@1.0.0` that binds it at `Task_AssessRepairability` under
its existing `review_after` gate. Onboarded clean through the registry front door (validates → ACTIVE).
The existing `cap.payment.assess_beneficiary` and `wire-repair-standard` seed are **untouched**.

## Consequences

- **Genuine agentic execution, safely caged.** A bank-trustable node can now run an open-ended
  investigation, yet the committed artifact is schema-valid, egress-restricted, tool-whitelisted, human-
  reviewed, and memoized. The BPMN still dictates order/routing/gates — the harness never sees it.
- **CI-clean, no GPU/harness.** Fake runner is the default; the pilot pack onboards and drives to
  `End_Resolved` on the fake in unit tests. The real harness path is integration-gated.
- **`native` byte-identical**; existing contracts/packs/tests untouched (additive kind + new pilot pack).
- **`[confirm]` (Deep Agents SDK):** the structured-output parameter and the MCP-tool passing mechanism
  are undocumented; the real runner uses the confirmed `create_deep_agent`/`ainvoke` surface + standard
  LangGraph `recursion_limit` + prompt-and-host-validate, and marks the rest `# [confirm]` — no invented
  API. The exact `model=` string for the managed proxy and any token budget are also `# [confirm]`.

## Traps recorded for maintainers

1. **Orchestration stays deterministic.** The harness lives strictly inside one node and must emit a
   schema-valid artifact; it never chooses the next step, routes a gateway, or sees the BPMN as a
   todo-list. (§9.5's "harness as pack-authoring aid" is a separate dev-time idea — not this.)
2. **`deep_agent` is nemoclaw-only + HITL-gated + memoized — fail closed.** Enforced at onboarding
   (registry) *and* runtime (core refuses no-runner; executor requires a memo store; task runner refuses
   `none`). Never relax one without the others.
3. **Never commit a fresh agent run over the reviewed artifact.** Memoization is mandatory precisely
   because the loop is non-deterministic; the attempt-keyed memo (ADR-019) is what makes resume correct.
4. **Default `read_only`.** A side-effectful autonomous loop is refused unless the pack explicitly
   justifies it; even then the side effect stays deterministic + human-gated (never let the loop move
   money).
5. **Don't invent the Deep Agents SDK.** Real harness behind `RealDeepAgentRunner`, integration-gated;
   the fake is the CI default. Unconfirmable surface stays `# [confirm]` + prompt-and-host-validate.
6. **Tool whitelist is the injection boundary.** Untrusted inputs make a deep_agent a prompt-injection
   surface; the egress + tool whitelist (derived from the contract) are the mitigation — keep them tight.
