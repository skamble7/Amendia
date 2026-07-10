# ADR-016 — Real, provider-agnostic LLM execution: polyllm + ConfigForge

- **Status:** Accepted
- **Date:** 2026-07-10
- **Related:** ADR-009/ADR-011 (agent-runtime foundation + execution — the `Executor` seam and the
  `llm`/`mcp`/`skill` capability kinds this fills), `amendia_platform_contracts_v1.md` (capability
  descriptors + artifact schemas), the agent-runtime execution pipeline reference
  (`amendia_agent_runtime_execution_pipeline.md`), and the operator guide
  `amendia_llm_configuration_guide.md` (how to configure/rotate models).
- **Advances:** the "real LLM path" that ADR-011 deliberately stubbed behind `AGENTRT_SIMULATION_MODE`
  ("*simulation seam — no external LLM/MCP calls*").

## Context

ADR-011 shipped the execution engine with capabilities running in **simulation**: `llm`-kind capabilities
returned deterministic canned artifacts through paired simulation skills. The only "real" path was a
hardcoded `ChatAnthropic(model="claude-sonnet-5")` block in the executor — single-vendor, single-model,
key read straight from `ANTHROPIC_API_KEY`, and not installed in the image (the `llm` extra was never
built). Turning it on meant a code change, and it locked the platform to one provider.

Two requirements drove this ADR:

1. **Real LLMs, in production.** The `llm` capabilities (draft repair / draft return / draft RFI / record
   resolution) must call a real model and produce schema-valid artifacts.
2. **Vendor-agnostic and config-driven.** Which provider/model/key a capability uses must be a
   configuration decision, changeable without redeploying or rebuilding — no vendor lock-in in code.

An internally-developed library, **polyllm** (a config-driven, LangChain-backed, provider-agnostic LLM
client), and a **ConfigForge** service (a platform config registry) already existed to solve exactly
this. This ADR adopts both and rewires the executor onto them.

## Decision

### Part A — ConfigForge as the model-config registry (`:8040`)

`backend/services/platform/config-forge-service` (FastAPI + Mongo, DB `ConfigForge`) is brought into the
stack (compose service `config-forge`, healthcheck on `/healthz`, `depends_on: mongodb`). It stores
**config entries** addressed by a **canonical ref**:

```
{env}.{kind}[.{provider}][.{platform}].{name}      e.g. dev.llm.bedrock.explicit-creds
```

The load-bearing endpoint is `GET /config/resolve/{ref}` → the entry, whose `data` field is a polyllm
**`ModelProfile`** (provider, model, temperature, `max_tokens`, `json_mode`, secret refs, region, …).
Default LLM profiles are loaded by `scripts/seed.py` (OpenAI / Google GenAI / Bedrock / Vertex
placeholder), all using `env:*` secret refs so **no secrets live in the seed**.

**Secrets are never stored inline in code.** `ModelProfile` fields (`api_key_ref`, `secret_refs`) hold
scheme-prefixed references resolved at call time: `env:VAR`, `file:/path#key`, or `literal:<value>`
(dev-only, pre-Vault). Migrating `literal:` → a future `vault:` scheme is a ConfigForge edit, not a code
change.

### Part B — polyllm as the provider adapter (`libs/polyllm`)

The library is vendored into the monorepo (`libs/polyllm`, its own `pyproject`, src-layout). Shape:

- **`ModelProfile` / `PolyllmConfig`** — non-secret model config + secret *references*.
- **Provider adapters** (`providers/{openai,google_genai,bedrock,google_vertexai}.py`) — map a profile to
  a LangChain chat model; `registry.py` dispatches on `provider`. **There is no direct `anthropic`
  provider yet** — Claude is reached via **Bedrock** (`us.anthropic.claude-*`).
- **`SecretProvider` chain** (`literal` → `env` → `file`) resolves the refs.
- **`RemoteConfigLoader(base_url).load(ref)`** — `GET {base_url}/config/resolve/{ref}`, builds the
  `ModelProfile` from `payload["data"]`, returns a ready `LLMClient`. `LLMClient.chat(messages)` →
  `ChatResult(text, raw)`. `json_mode` yields clean JSON (native for OpenAI/GenAI; fence-stripped for
  Bedrock).

### Part C — the executor rewire (`agent-runtime/app/engine/executor/dispatch.py`)

`_execute_llm_real` replaces the `ChatAnthropic` block. For each declared output artifact it prompts the
model for a single JSON object **constrained by that artifact's JSON Schema**, parses it, and hands it to
the normal `_validate` step. Key mechanics:

- **Config ref selection — the platform rule:** `ref = descriptor.runtime.model_config_key or
  settings.LLM_CONFIG_REF`. **The capability's own declaration wins; when it declares nothing, the runtime
  default is used.** Clients are cached **per ref**, so different capabilities can run on different models.
- **Schema in the prompt.** The output `json_schema` (which lived only in `OutputSpec`, not in the
  executor's view) is now threaded through `ExecutionContext.extras["output_schemas"]` from
  `task_runner._run_capability`, so the model generates schema-valid data.
- **Sync↔async bridge.** LangGraph nodes are synchronous and the engine runs them via
  `asyncio.to_thread` (worker thread, no running loop), so `_run_blocking` uses `asyncio.run`; it also
  guards the (unexpected) running-loop case by isolating the coroutine on a fresh thread.
- **Robust JSON parse.** polyllm strips Bedrock fences under `json_mode`; `_parse_json` is a
  provider-agnostic safety net (fences / surrounding prose).

### Part D — `mcp` falls back to simulation (bridge)

Real MCP has no client yet. Rather than hard-fail a real run at the one `mcp` capability
(`sanctions_screen`), `_execute_llm_real`'s sibling branch logs a **warning and falls back to the paired
simulation skill**, so the flow completes end-to-end. `skill`-kind side-effectful capabilities
(`apply_repair`, `notify_parties`, `execute_return`) remain their simulated implementations — no real
payment side effects in dev.

### Part E — config, deps, deploy

- **`agent-runtime/app/config.py`** — adds `CONFIG_FORGE_URL` and `LLM_CONFIG_REF`
  (default `dev.llm.bedrock.explicit-creds`).
- **Dependencies** — `polyllm[langchain,remote]` (an editable path source) replaces the
  `langchain-anthropic` extra; pre-installed in the Dockerfile (path dep, not on any index).
- **Compose** — `agent-runtime` gains `AGENTRT_SIMULATION_MODE: "false"`,
  `AGENTRT_CONFIG_FORGE_URL: http://config-forge:8040`,
  `AGENTRT_LLM_CONFIG_REF: dev.llm.bedrock.explicit-creds`, and `depends_on: config-forge (healthy)`.

## Consequences

- **Real, provider-agnostic LLM execution — verified live end-to-end.** A driven AC01 exception ran to
  `outcome=End_Resolved`, with `Task_DraftRepair` and `Task_RecordResolution` both logging
  `real LLM [dev.llm.bedrock.explicit-creds] (bedrock:us.anthropic.claude-sonnet-4-5-…) produced <artifact>`
  and passing schema validation; the ConfigForge resolve + `~5 s` Bedrock latency corroborate a real call.
  Switching the whole platform to GPT-4o or Gemini is a one-line `AGENTRT_LLM_CONFIG_REF` change (or a
  `PUT /config/{id}` on the referenced entry) — **no code, no image rebuild**.
- **Per-capability model routing is available** via the descriptor's `model_config_key`; unset today, so
  every `llm` capability falls back to the runtime default.
- **Deliberately deferred:**
  - **A direct `anthropic` provider in polyllm** — Claude runs via Bedrock for now (needs AWS creds/region
    + model access). Adding it is a new polyllm adapter + a ConfigForge entry; no agent-runtime change.
  - **Real MCP execution** (sanctions) — simulation fallback until an MCP client lands.
  - **LLM output memoization across HITL resumes** — see trap (2).
- **Traps recorded for maintainers:**
  1. **Secrets are references, never values.** Keep `api_key_ref`/`secret_refs` as `env:`/`file:` in real
     deployments; `literal:` is a dev convenience only. Never commit a key into a descriptor or the seed.
  2. **`review_after` re-runs the capability on resume.** LangGraph re-executes an interrupted node from
     the top, so an approved `llm` node calls the model **again** on resume — extra cost/latency, and the
     regenerated (non-deterministic) artifact, not the one the human reviewed, is what commits. Fine in
     simulation (deterministic); for real LLMs, memoize the produced artifact per (element, inputs) within
     the instance so resume reuses it. Deferred.
  3. **Descriptor changes are immutable** — onboarding skips already-registered versions. Changing a
     capability's `model_config_key` requires re-onboarding (drop the `amendia` DB — **not** ConfigForge's
     DB — and restart the registry). ConfigForge entries, by contrast, are mutable via `PUT`.
  4. **Sync node calling async polyllm** relies on the engine running nodes in a worker thread
     (`asyncio.to_thread`); `_run_blocking` must keep handling both no-loop and running-loop cases.
  5. **`kind` matters.** Only `llm` capabilities route to the real model; `mcp` falls back to simulation,
     and `skill` capabilities always run their (simulated, side-effect-guarded) functions.
