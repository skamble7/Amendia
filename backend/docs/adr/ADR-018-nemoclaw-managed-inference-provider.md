# ADR-018 — NemoClaw managed-inference provider for polyllm (Nemotron, config-selectable)

- **Status:** Accepted
- **Date:** 2026-07-10
- **Related:** **ADR-016** (polyllm + ConfigForge — the provider-adapter/registry substrate,
  `ModelProfile`, `SecretProvider`, `RemoteConfigLoader`, and the ref-selection rule this consumes),
  **ADR-017** (the `native`/`nemoclaw` execution mode — the module-level `run_real_llm(...)` and the
  `CapabilityRunSpec` ref plumbing, Part F, that make this provider usable with no agent-runtime change),
  `amendia_secure_runtime_nemoclaw_plan.md` (v2) §6, `amendia_llm_configuration_guide.md`,
  `libs/polyllm/README.md`.
- **Advances:** ADR-017 Phase 2 — adds **Nemotron 3 Ultra** (and any model behind an OpenAI-compatible
  NVIDIA NIM / OpenShell managed-inference endpoint) as a **config-selectable** LLM peer to
  Bedrock/OpenAI/Gemini.

## Context

ADR-016 made model choice pure configuration: a `ModelProfile` in ConfigForge, addressed by canonical
ref, resolved by polyllm's provider **registry** (`registry.py` dispatches on `provider`). ADR-017 then
(a) routed every real LLM call through a module-level `run_real_llm(ref, …)` → ConfigForge → polyllm
(cached per ref), (b) threaded the selected ref into `CapabilityRunSpec`, and (c) had the
`FakeOpenShellClient` reuse `run_real_llm`. The consequence: a **new polyllm provider + a ConfigForge ref
is all that is needed** for a `nemoclaw` ref to work — in `native` mode (`InProcessExecutor`) **and** in
`nemoclaw`-mode-with-the-fake — with **zero agent-runtime code change**.

The NemoClaw blueprint's economic argument (Nemotron's ~10× cost/perf, measured on the Deep Agents
harness) motivates making Nemotron a first-class, per-capability-selectable option now, so Phase 4's
`deep_agent` capabilities can pair with it later by config alone.

## Decision

### Part A — polyllm `nemoclaw` provider adapter (`libs/polyllm/.../providers/nemoclaw.py`)

`NemoClawAdapter` maps a `ModelProfile` to a LangChain chat model for an **OpenAI-compatible** endpoint,
reusing `langchain_openai.ChatOpenAI` parameterised on **`base_url`** (required) rather than a bespoke
client. Supports `model`, `base_url`, `temperature`, `max_tokens`, `timeout_seconds`, `max_retries`,
`json_mode`, `headers` (marked `# [confirm]`), `provider_options`, and `api_key_ref`. Registered in
`registry.py` under `"nemoclaw"`. `LLMClient.chat(...) -> ChatResult(text, raw)` is unchanged.

### Part B — `json_mode` (Bedrock-style)

NIM / managed-proxy support for OpenAI `response_format` is unconfirmed, so the adapter does **not** rely
on a provider JSON-mode API. Instead `client.py` strips code fences post-response for
`provider in ("bedrock", "nemoclaw")` — handling both native-JSON and fenced replies. A profile whose
endpoint is known to support `response_format` can still opt in via `provider_options`.

### Part C — two-mode credential handling

- **Direct / native (usable now):** `api_key_ref` (e.g. `env:NVIDIA_NIM_API_KEY`) resolves host-side via
  the existing `SecretProvider` chain, exactly like other providers.
- **In-sandbox managed proxy (deferred):** the OpenShell gateway brokers/scopes the token so the sandbox
  never holds it; the host is **not** required to supply one. Modelled as config: when no host-side token
  resolves, the adapter uses a **non-secret placeholder** rather than failing, so the profile builds and
  the gateway injects the real scoped token in the in-sandbox path. The mechanism is `# [confirm]` and
  activates with the real `HttpOpenShellClient` (ADR-017 Phase 5). No secret is ever embedded in a
  profile — only a reference or a non-secret placeholder.

### Part D — ConfigForge seed profiles (`config-forge-service/scripts/seed.py`)

Two idempotent (skip-existing) `env:`-ref-only profiles:
- `dev.llm.nemoclaw.nemotron-ultra` — managed proxy (`inference.local/v1`), `api_key_ref:
  env:OPENSHELL_INFERENCE_TOKEN`, `json_mode: true`, `max_tokens: 32000`. The in-sandbox target.
- `dev.llm.nemoclaw.nim` — a **directly-reachable** NIM endpoint (`api_key_ref: env:NVIDIA_NIM_API_KEY`)
  — the profile a developer can actually hit today (host → NIM). Model id / base URLs are `# [confirm]`.

### Part E — selection (verified, not rebuilt)

The ADR-016 rule (`descriptor.runtime.model_config_key or settings.LLM_CONFIG_REF`) and the
`run_real_llm` dispatch already exist and are **unchanged**. Confirmed with mocks (a fake
`langchain_openai` + a patched `_llm_client`) that: `AGENTRT_LLM_CONFIG_REF=<nemoclaw ref>` routes every
defaulting `llm` capability to the new provider in **both** `native` and `nemoclaw`(fake) modes; a
per-capability `runtime.model_config_key` routes just that capability; client caching stays per-ref.

## Consequences

- **Nemotron is now a config choice.** A one-line `AGENTRT_LLM_CONFIG_REF` swap (or a per-capability
  `model_config_key`) moves any/all `llm` capabilities to Nemotron and back — no code, no rebuild — the
  same lever that already switches OpenAI/Gemini/Bedrock. Claude still runs via Bedrock; Nemotron is a
  peer option, not a replacement.
- **Works today via a directly-reachable NIM**, and through the fake sandbox path; both proven with
  fully-mocked unit tests (no live NIM/GPU in CI).
- **Purely additive.** Existing providers, refs, and the default `dev.llm.bedrock.explicit-creds` are
  unchanged; the executor/task-runner were **not** touched (ADR-017 already carries the ref). With no
  `nemoclaw` ref selected, nothing changes.
- **A credential-surface improvement is scaffolded:** the managed-proxy profile needs no host-side token
  because the gateway brokers it — the ADR-017 §7 win — realized end-to-end only when the real client
  lands.
- **Deliberately deferred / `[confirm]`:**
  - The **in-sandbox managed-proxy leg** (`inference.local/v1`) end-to-end depends on the real
    `HttpOpenShellClient` (ADR-017 Phase 5, still a guarded scaffold).
  - **Gateway credential-brokering specifics** (how the scoped token is injected) — `# [confirm]`.
  - Exact **Nemotron model ids**, hosted **NIM base URL**, managed-proxy path, and any NemoClaw-specific
    **auth headers** — `# [confirm]` against live docs.
  - **`deep_agent` pairing** (ADR-017 Phase 4) — where Nemotron-on-Deep-Agents economics land.

## Traps recorded for maintainers

1. **Secrets stay references.** `nemoclaw` profiles carry `env:` refs (or the gateway-brokered
   placeholder) — never a key value. Do not "fix" the placeholder by hardcoding a token; the direct path
   uses `env:NVIDIA_NIM_API_KEY`, the managed-proxy path is brokered by the gateway.
2. **`base_url` is mandatory** for `nemoclaw` (OpenAI-compatible endpoint). A profile without it fails
   fast by design.
3. **`json_mode` ≠ a provider API here.** Clean JSON comes from fence-stripping in `client.py`
   (`provider in ("bedrock","nemoclaw")`), not a NIM `response_format`. If you add a provider that *does*
   guarantee JSON natively, don't lump it into that branch.
4. **Descriptor edits ⇒ re-onboarding** (ADR-016 trap 3). Moving a capability to a `nemoclaw` ref via
   `model_config_key` is a descriptor change and needs re-onboarding; a platform-wide swap via
   `AGENTRT_LLM_CONFIG_REF` (or editing the ConfigForge entry) does not.
5. **Selection logic is ADR-016/017's — don't fork it.** This ADR only *registers a provider*; the ref
   dispatch flows through the existing `run_real_llm`. Keep it that way so `native` and `nemoclaw`(fake)
   stay identical.
