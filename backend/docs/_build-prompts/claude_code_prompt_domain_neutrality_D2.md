# Claude Code Prompt — ADR-047 D2: re-home in-code capabilities onto MCP, delete the domain code

Implement ADR-047 **D2** (see `ADR-047-D2-elaboration-runtime-capability-decoupling.md`). This is the last
domain-neutrality leak: the seed's in-process capability logic (`agent-runtime/app/capabilities/*`, the
`deep_agent` in-code tools, `SIM_CAPABILITIES`/`KNOWN_WORKER_TOOLS`). Re-home it onto the existing
`wire_transfer_exception` MCP server, **re-onboard the seed packs as MCP-backed data (per-tool + `input_map`)**,
then delete the code. This restructures the runtime image and re-onboards every seed — do it as its own pass,
behind the regression net in Step 0. Approach is **per-tool + `input_map`** (the validated `ws-stan` shape), not
reshaping stub schemas.

## Step 0 · Regression net FIRST (do not skip)

Before changing anything, capture a **golden outcome** per seed pack. For `wire-repair-standard` (and `-agentic`,
`-dmn`, `-screening`), run a representative sample exception per gateway branch — repairable, unrepairable,
needs-info, and a screening-hit — through the current skill-backed packs and record: terminal outcome
(`End_Resolved`/`End_Returned`/…), the produced-artifact set, and the HITL task sequence. Persist these as a
golden fixture. The MCP-backed re-onboarded packs must reproduce the **same** outcomes for the same inputs — that
equivalence is the acceptance bar, not just "tests green."

## Step 1 · MCP server exposes every tool the seeds bind

Audit which capabilities each seed pack binds. In the `wire_transfer_exception` MCP server, ensure a
Guideline-compliant tool exists for every **`skill`-kind** seed capability (enrich, assess, apply_repair,
execute_return, notify_parties, sanctions/screen, draft_rfi if skill, …) **and** for the `deep_agent` in-code tools
(`search_payment_history`, `name_match`, and any others the deep_agent runner calls). Each tool: declared
`inputSchema`/`outputSchema`, closed shapes, acknowledgement shape on side-effectful actions, and `isError` +
conventional `error_code` for the modeled business errors the seed routes on (screening hit, payment rejected,
needs-info). Port the exact behavior from the in-code modules so outcomes match Step 0. (`llm`/`deep_agent`
*capabilities* stay descriptor-driven — only their in-code **tool functions** move to the server.)

## Step 2 · Re-onboard each seed pack as MCP-backed data (per-tool + `input_map`)

For each seed pack, produce a new manifest (the `ws-stan` pattern, per the runbook):
- `skill` caps → `mcp` caps with `endpoint` = the server and `runtime.tools` whitelisting their tool; `llm` /
  `deep_agent` caps unchanged.
- Register the per-tool `<tool>_input/output` artifact schemas (from introspection); **replace** the old bespoke
  shared-artifact schemas (`art.payment.investigation_dossier`, etc.) where they were only serving the skill
  chaining. Keep any artifact still referenced by an `llm`/`deep_agent`/gateway path.
- Author the **`input_map`** (ADR-048): entry task ← trigger; downstream ← upstream tool output (field-level). Set
  **side-effect flags** on the action tools (so the `approve_actions` floor engages), the **gateway variable**, and
  schema-valid **triage** rules. Declare the pack's **trigger artifact** (D1) so triage validates against it.
- These re-onboarded manifests + schemas **replace** the old seed data under `agent-runtime/seed/`. Update the
  seeder counts/fixtures accordingly.

## Step 3 · Delete the in-code capability layer

- Delete `agent-runtime/app/capabilities/*` (all modules: `wire_repair/*`, `screening.py`, `payment_comp.py`,
  `composition.py`), `SIM_CAPABILITIES`, `KNOWN_WORKER_TOOLS`, and the P1-leftover hardcoded `deep_agent` tool
  whitelist (`validation/deep_agent.py`).
- Remove every engine import of them (`executor/core.py`, `executor/deep_agent.py`, `executor/openshell/client.py`,
  `task_runner`, …). The L5-leftover payload-path reads (`mcp_client.py`, `screening.py`, `payment_comp.py`)
  disappear with the files. The runtime keeps only the generic `mcp`/`llm`/`deep_agent` executors — they resolve
  everything from the descriptor + the MCP server.

## Step 4 · Move capability tests to the fixture layer (preserve coverage)

- Move the three in-code-capability test files to the MCP server's own suite or an integration fixture. **Port** the
  meaningful behavioral cases — the screening-hit business error, the apply_repair/execute_return acknowledgement,
  the deep_agent investigative path — don't drop them. Delete only tests that assert in-process implementation
  details that no longer exist.

## Step 5 · Verify

- `grep -rE "wire|repair|dossier|sanction|payment|SIM_CAPABILITIES|capabilities\.wire_repair"
  backend/services/agent-runtime/app` → only generic docstring examples; no import/registry/reference to a
  wire/payment capability.
- **Golden equivalence:** each re-onboarded seed pack runs the Step-0 sample exceptions to the **same** terminal
  outcomes + artifact sets + HITL sequences.
- A fresh-domain, fresh-MCP process still onboards → validates → activates → executes with zero platform change
  (standing ADR-047 test).
- `registry`, `webui`, `agent-runtime` green (excluding the known live-stack e2e); ported capability tests pass.

## Non-goals / cautions

- No behavior change to any seed process — the re-home must be outcome-equivalent (Step 0 enforces this). Read
  every engine-test failure from the `SIM_CAPABILITIES` removal before deleting the test — some are coverage to
  **port**, not drop. No in-process plugin loader (deferred). No reshaping stub schemas to preserve the old
  shared-artifact contract (rejected in the ADR).

## Definition of done

Platform code scan clean of domain capabilities; every seed pack runs MCP-backed to its golden outcomes; the
standing fresh-pack zero-platform-change test holds; suites green; ADR-047 marked D2 shipped; the D2 elaboration
and the onboarding runbook referenced. The wire-transfer process is now, in full, just another onboarded pack +
fixture.
