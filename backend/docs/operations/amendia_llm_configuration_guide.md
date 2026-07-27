# Configuring LLMs for the Amendia platform

A practical guide for configuring, rotating, and troubleshooting the language models the agent-runtime
uses. Audience: platform / ops engineers. No agent-runtime code changes are needed for anything in this
guide — **models are configuration, not code**.

For the design rationale see **ADR-016**. For the library internals see `libs/polyllm/README.md`.

---

## 1. The mental model (30 seconds)

```
capability (agent-runtime)                    ConfigForge (:8040)              Provider
   │  ref = model_config_key                     │                              │
   │        OR runtime default  ─── resolve ───▶  │  ModelProfile (data) ──▶ polyllm ──▶ OpenAI / Gemini
   │                                              │  (provider, model, keys…)             / Bedrock(Claude)
```

- **ConfigForge** is a registry of model configs, each addressed by a **canonical ref**. It stores the
  *non-secret* config plus **references** to secrets — never raw keys in code.
- **polyllm** (in the agent-runtime) fetches a config by ref, resolves the secret refs, and calls the
  right provider.
- The agent-runtime picks the ref like this: **the capability's declared `model_config_key` wins; if it
  declares nothing, the runtime default (`AGENTRT_LLM_CONFIG_REF`) is used.**

You configure models by creating/editing **ConfigForge entries** and pointing the runtime (or a
capability) at the right **ref**.

---

## 2. The canonical ref

```
{env}.{kind}[.{provider}][.{platform}].{name}
```

| Segment    | Required | Examples                                   |
|------------|----------|--------------------------------------------|
| `env`      | yes      | `dev`, `staging`, `prod`                   |
| `kind`     | yes      | `llm`                                      |
| `provider` | optional | `openai`, `google_genai`, `bedrock`        |
| `platform` | optional | `payments`, `raina`                        |
| `name`     | yes      | `default`, `fast`, `explicit-creds`        |

Examples: `dev.llm.openai.default`, `dev.llm.bedrock.explicit-creds`, `prod.llm.payments.default`.

---

## 3. Where things live

| Thing | Location |
|---|---|
| ConfigForge service | `backend/services/platform/config-forge-service` · compose service `config-forge` · **`http://localhost:8040`** |
| Seed of default profiles | `config-forge-service/scripts/seed.py` |
| polyllm library | `libs/polyllm` (`README.md` = full `ModelProfile` reference) |
| Runtime default ref | `AGENTRT_LLM_CONFIG_REF` (compose) / `config.py: LLM_CONFIG_REF` |
| ConfigForge URL (runtime) | `AGENTRT_CONFIG_FORGE_URL` (compose) |
| Real-vs-sim switch | `AGENTRT_SIMULATION_MODE` (`false` = real LLM) |
| Per-capability override | `runtime.model_config_key` in a capability descriptor (`seed/wire-repair-standard/capabilities/*.json`) |

---

## 4. Common tasks

Base URL below is `CF=http://localhost:8040`.

### 4a. See what's configured

```bash
curl -s "$CF/config/?kind=llm" | jq -r '.[] | "\(.ref)  ->  \(.data.provider):\(.data.model)"'
curl -s "$CF/config/resolve/dev.llm.bedrock.explicit-creds" | jq .data     # one entry's ModelProfile
```

### 4b. Add a new model config

`POST /config/` with `data` = a polyllm `ModelProfile`. The ref is built from `env`/`kind`/`provider`/
`platform`/`name`.

```bash
curl -s -X POST "$CF/config/" -H 'Content-Type: application/json' -d '{
  "env": "dev", "kind": "llm", "provider": "openai", "name": "default",
  "description": "Default OpenAI GPT-4o",
  "data": {
    "provider": "openai", "model": "gpt-4o", "temperature": 0.1,
    "api_key_ref": "env:OPENAI_API_KEY"
  }
}'     # -> ref: dev.llm.openai.default
```

### 4c. Change a model or key (no redeploy)

Rotate the model / temperature / key **in place** — every capability using that ref picks it up on the
next call (client cache is per-process; restart agent-runtime to force a refresh):

```bash
ID=$(curl -s "$CF/config/resolve/dev.llm.openai.default" | jq -r ._id)
curl -s -X PUT "$CF/config/$ID" -H 'Content-Type: application/json' \
  -d '{"data": {"provider":"openai","model":"gpt-4o-mini","temperature":0.1,"api_key_ref":"env:OPENAI_API_KEY"}}'
```

### 4d. Re-seed the default profiles

```bash
docker compose -f backend/deploy/docker-compose.yml run --rm config-forge \
  python scripts/seed.py --mongo-uri mongodb://mongodb:27017 --db ConfigForge --env dev
```

Idempotent — it skips refs that already exist.

---

## 5. Choosing which model the platform uses

### Platform-wide default

Point the runtime default at any ref:

```yaml
# backend/deploy/docker-compose.yml → agent-runtime.environment
AGENTRT_LLM_CONFIG_REF: dev.llm.bedrock.explicit-creds   # or dev.llm.openai.default, dev.llm.google_genai.default
```

Restart agent-runtime. Every `llm` capability that doesn't declare its own model now uses this.

### Per-capability override (optional)

Give one capability its own model by setting `model_config_key` in its descriptor to a real ConfigForge
ref:

```jsonc
// seed/wire-repair-standard/capabilities/cap.payment.draft_rfi.json
"runtime": { "kind": "llm", "prompt_key": "…",
             "model_config_key": "dev.llm.openai.fast",   // this capability → GPT-4o-mini
             "structured_output": true }
```

The runtime **honors the declaration**; capabilities with `model_config_key: null` **fall back** to the
runtime default. So you can, e.g., keep `draft_repair` on Claude/Bedrock for quality and move `draft_rfi`
to `dev.llm.nemoclaw.nim` for cost — a pure config change, no code, in `native` mode **and**
`nemoclaw`(fake) mode alike (both resolve the ref through the same `run_real_llm` path).

> ⚠️ **Descriptors are immutable once onboarded.** To apply a descriptor change you must re-onboard:
> ```bash
> CF=backend/deploy/docker-compose.yml
> docker compose -f $CF build process-registry            # seed is baked into the image
> docker compose -f $CF stop process-registry agent-runtime
> docker compose -f $CF exec -T mongodb mongosh amendia --quiet --eval "db.dropDatabase()"   # NOT the ConfigForge DB
> docker compose -f $CF up -d --force-recreate identity process-registry agent-runtime
> ```
> This drops only the `amendia` DB (transient workflow data + identity, both re-seeded on startup);
> **ConfigForge's DB is separate and untouched.**

---

## 6. Providers & example ModelProfiles

polyllm supports **`openai`**, **`google_genai`**, **`bedrock`**, **`nemoclaw`** (and a
`google_vertexai` placeholder). **There is no direct Anthropic-API provider yet — run Claude via
Bedrock; Nemotron is now a peer option via `nemoclaw`.** Full field reference: `libs/polyllm/README.md`.

```jsonc
// OpenAI
{ "provider": "openai", "model": "gpt-4o", "temperature": 0.1, "api_key_ref": "env:OPENAI_API_KEY" }

// Google Gemini
{ "provider": "google_genai", "model": "gemini-1.5-pro", "temperature": 0.1, "api_key_ref": "env:GOOGLE_API_KEY" }

// Claude on AWS Bedrock (explicit IAM creds) — the current platform default
{ "provider": "bedrock", "transport": "bedrock",
  "model": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
  "temperature": 0.1, "max_tokens": 32000, "aws_region": "us-east-1", "json_mode": true,
  "secret_refs": { "access_key": "env:AWS_ACCESS_KEY_ID", "secret_key": "env:AWS_SECRET_ACCESS_KEY" } }

// Nemotron 3 Ultra via NemoClaw (OpenAI-compatible: NVIDIA NIM or the OpenShell managed proxy)
// ref: dev.llm.nemoclaw.nim — directly reachable, usable today (host → NIM)
{ "provider": "nemoclaw", "transport": "direct",
  "model": "nvidia/nemotron-3-ultra", "base_url": "https://integrate.api.nvidia.com/v1",
  "temperature": 0.1, "max_tokens": 32000, "json_mode": true,
  "api_key_ref": "env:NVIDIA_NIM_API_KEY" }
```

Notes: set **`json_mode: true`** for capability profiles — the runtime asks for JSON artifacts, and this
guarantees clean JSON (native for OpenAI/Gemini; fence-stripped for Bedrock **and `nemoclaw`**). Bedrock
may also use `aws_profile` or ambient IAM instead of `secret_refs`.

**`nemoclaw` credential modes (ADR-018):** `nemoclaw` is an OpenAI-compatible endpoint, so it always
needs a `base_url`. Two modes:
- **Direct / native — usable now.** `api_key_ref` (e.g. `env:NVIDIA_NIM_API_KEY`) resolves host-side like
  any provider; point `base_url` at a reachable NIM. This is `dev.llm.nemoclaw.nim`.
- **In-sandbox managed proxy — deferred (ADR-017 Phase 5).** `dev.llm.nemoclaw.nemotron-ultra` targets the
  OpenShell managed proxy (`inference.local/v1`); the gateway brokers/scopes the token
  (`OPENSHELL_INFERENCE_TOKEN`) so the sandbox never holds it, and **no host-side token is required**.
  This leg activates with the real `HttpOpenShellClient`; today the profile is reachable only if that
  proxy URL is routable from the host. Model id / proxy path are `# [confirm]` against live NemoClaw docs.

Nemotron via managed inference is the intended pairing for **`deep_agent` capabilities (ADR-017 Phase 4)**
— its ~10× cost/perf claim is measured on the Deep Agents harness.

---

## 7. Secrets (never store raw keys in code)

`ModelProfile` never holds a secret value — only a **reference**, resolved at call time:

| Scheme     | Example                         | Resolved from            | Use |
|------------|---------------------------------|--------------------------|-----|
| `env:`     | `env:OPENAI_API_KEY`            | environment variable     | **preferred** — deployment-managed |
| `file:`    | `file:/run/secrets/keys.json#openai` | JSON file on disk   | Docker/mounted secrets |
| `literal:` | `literal:sk-…`                  | the ref itself           | **dev only**, pre-Vault |

Whatever a profile references (e.g. `env:OPENAI_API_KEY`, `env:AWS_ACCESS_KEY_ID`,
`env:NVIDIA_NIM_API_KEY`) must be present in the **agent-runtime** container's environment. Prefer
`env:`/`file:` in real deployments; `literal:` is a convenience for local dev only.

**One deliberate exception (ADR-018):** a `nemoclaw` profile aimed at the OpenShell *managed proxy*
(`dev.llm.nemoclaw.nemotron-ultra`) does **not** require its token host-side — the OpenShell gateway
brokers and scopes it into the sandbox so real secrets never enter the agent-runtime container (the
credential-surface upgrade ADR-017 §7 anticipated). That leg is deferred until the real `HttpOpenShellClient`
lands; the *direct* NIM profile (`dev.llm.nemoclaw.nim`) does need `NVIDIA_NIM_API_KEY` host-side.

---

## 8. Turning real LLMs on / off

```yaml
AGENTRT_SIMULATION_MODE: "false"   # real LLM (via ConfigForge/polyllm)
AGENTRT_SIMULATION_MODE: "true"    # deterministic simulation (no external calls) — for tests/CI
```

`skill`-kind side-effectful capabilities (apply-repair, notify, execute-return) always run their
simulated implementations, and `mcp` (sanctions) falls back to simulation regardless — so nothing makes a
real payment or a real sanctions call yet.

---

## 9. Verify it's working

```bash
# 1) config resolves
curl -s "$CF/config/resolve/dev.llm.bedrock.explicit-creds" | jq '.data.provider, .data.model'
```

Then drive an exception through to an `llm` capability (e.g. approve the "Assess repairability" gate so
`Task_DraftRepair` runs) and look for this in the agent-runtime logs — **this line proves a real call**:

```
[Task_DraftRepair] real LLM [dev.llm.bedrock.explicit-creds]
    (bedrock:us.anthropic.claude-sonnet-4-5-20250929-v1:0) produced art.payment.repair_instruction
```

The preceding `GET http://config-forge:8040/config/resolve/… 200` + `loaded LLM profile '…'` lines show
the ConfigForge fetch. A multi-second latency (vs. sub-ms simulation) is a further tell.

---

## 10. Troubleshooting

| Symptom (in agent-runtime logs) | Cause | Fix |
|---|---|---|
| `Config not found: <ref>` / `404` from `/config/resolve` | The ref the capability/runtime uses isn't in ConfigForge | Create it (§4b) or fix `AGENTRT_LLM_CONFIG_REF` / `model_config_key` |
| `… requires an API key` / auth error | The profile's `api_key_ref`/`secret_refs` env var isn't set in the agent-runtime container | Add the env var, or switch the ref to a `literal:`/`file:` you control |
| Bedrock `AccessDenied` / model-not-found | Creds/region lack Bedrock access or the model isn't enabled in that account/region | Enable model access in AWS, fix `aws_region`, or point at a different provider ref |
| `nemoclaw requires base_url` | A `nemoclaw` profile has no `base_url` | Set `base_url` to your NIM endpoint or the managed proxy (`https://inference.local/v1`) |
| NemoClaw connection/timeout to `base_url` | The NIM/managed-proxy endpoint isn't reachable from the agent-runtime container | Use the directly-reachable `dev.llm.nemoclaw.nim` profile with a valid `base_url`; the `inference.local/v1` proxy leg needs the real OpenShell client (ADR-017 Phase 5) |
| NemoClaw 401/403 (auth) | `NVIDIA_NIM_API_KEY` not set (direct), or token not brokered (in-sandbox) | Set the env var for the direct profile; the managed-proxy profile relies on the gateway injecting a scoped token (deferred) |
| `LLM returned non-JSON …` | Model didn't emit clean JSON | Set `json_mode: true` on the profile; consider a stronger model |
| `… schema_invalid` after a real call | Model output didn't match the artifact schema | Stronger model / lower temperature; the schema is already sent in the prompt |
| `MCP capability … using simulation fallback` (WARNING) | Expected — no real MCP client yet | None (by design) |
| Model change didn't take effect | polyllm caches the client per ref per process | Restart agent-runtime (or it refreshes on next process) |

---

## 11. Known caveats

- **Claude is Bedrock-only** for now (no direct Anthropic provider in polyllm).
- **`review_after` re-runs the capability on resume** — a real LLM node is called again when the reviewer
  approves, so the committed artifact is a fresh generation, not the exact one reviewed (near-identical at
  low temperature). Memoization is a planned fix (ADR-016, trap 2). Prefer low `temperature` meanwhile.
- **Descriptor edits require re-onboarding** (§5); ConfigForge edits do not.
