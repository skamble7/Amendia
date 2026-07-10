# polyllm

A config-driven, provider-agnostic LLM client. Swap providers and models via configuration — no code changes in your application logic.

---

## Contents

1. [Install](#install)
2. [Supported Providers](#supported-providers)
3. [Usage — Inline Config](#usage--inline-config)
4. [Usage — ConfigForge (Recommended)](#usage--configforge-recommended)
5. [Secret Reference Schemes](#secret-reference-schemes)
6. [ModelProfile Reference](#modelprofile-reference)
7. [Provider-Specific Notes](#provider-specific-notes)
8. [Migration: Inline → ConfigForge](#migration-inline--configforge)

---

## Install

```bash
# Core + LangChain backends
pip install polyllm[langchain]

# Add ConfigForge remote loader (requires httpx)
pip install polyllm[langchain,remote]
```

---

## Supported Providers

| `provider` value | Backend | Status |
|-----------------|---------|--------|
| `openai` | `langchain-openai` | Active |
| `google_genai` | `langchain-google-genai` | Active |
| `bedrock` | `langchain-aws` | Active |
| `google_vertexai` | `langchain-google-vertexai` | Placeholder — not yet active |

---

## Usage — Inline Config

Pass a full `PolyllmConfig` directly. Useful for local development or when ConfigForge is not available.

```python
from polyllm import LLMClient, PolyllmConfig

cfg = PolyllmConfig(
    default_profile="default",
    profiles={
        "default": {
            "provider": "openai",
            "model": "gpt-4o",
            "temperature": 0.1,
            "api_key_ref": "env:OPENAI_API_KEY",
        }
    },
)

client = LLMClient(cfg)

result = await client.chat([
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello"},
])

print(result.text)
```

### Multiple profiles

```python
cfg = PolyllmConfig(
    default_profile="fast",
    profiles={
        "fast": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_key_ref": "env:OPENAI_API_KEY",
        },
        "powerful": {
            "provider": "openai",
            "model": "gpt-4o",
            "api_key_ref": "env:OPENAI_API_KEY",
        },
    },
)

client = LLMClient(cfg)

# Uses default profile
result = await client.chat(messages)

# Override per-call
result = await client.chat(messages, profile="powerful")
```

---

## Usage — ConfigForge (Recommended)

`RemoteConfigLoader` fetches a `ModelProfile` from the ConfigForge service by **canonical ref** and returns a ready `LLMClient`. No config object is constructed in application code — the profile lives in ConfigForge.

Platform code only needs to carry the ref string. The ConfigForge URL is read from the `CONFIG_FORGE_URL` environment variable — no URL needs to be embedded in application code.

```python
from polyllm import RemoteConfigLoader

# CONFIG_FORGE_URL is read from the environment
loader = RemoteConfigLoader()

client = await loader.load("prod.llm.openai.astra.primary")

result = await client.chat([
    {"role": "user", "content": "Hello"},
])
```

### Constructor options

```python
RemoteConfigLoader(
    base_url=None,        # If omitted, reads CONFIG_FORGE_URL from environment
    timeout=5.0,          # HTTP timeout in seconds (default: 5.0)
    secrets=my_provider,  # Custom SecretProvider (default: composite env+file+literal)
)
```

### Canonical ref format

```
{env}.{kind}[.{provider}][.{platform}].{name}
```

| Segment | Required | Examples |
|---------|----------|---------|
| `env` | Yes | `prod`, `dev`, `staging`, `global` |
| `kind` | Yes | `llm`, `storage` |
| `provider` | Optional | `openai`, `anthropic`, `bedrock`, `google_genai` |
| `platform` | Optional | `raina`, `zeta`, `orko`, `astra` |
| `name` | Yes | `default`, `primary`, `fast` |

**Examples:**

```
prod.llm.openai.default             # shared OpenAI config for production
prod.llm.openai.astra.primary       # ASTRA's primary OpenAI config in prod
dev.llm.google_genai.default        # shared Gemini config for dev
prod.llm.bedrock.zeta.modernization # Zeta's Bedrock config in prod
```

---

## Secret Reference Schemes

Secrets are **never embedded in application code or passed directly**. Instead, `ModelProfile` fields like `api_key_ref` hold a scheme-prefixed reference string that is resolved at call time.

| Scheme | Format | Resolved from | Use case |
|--------|--------|---------------|---------|
| `env:` | `env:OPENAI_API_KEY` | Environment variable | Deployment-managed secrets |
| `literal:` | `literal:sk-abc123...` | Inline value | Keys stored directly in ConfigForge (temporary, pre-Vault) |
| `file:` | `file:/run/secrets/keys.json#openai` | JSON file on disk | Docker secrets / mounted volumes |

**Future:** `vault:secret/llm/openai#api_key` — HashiCorp Vault integration (planned). Migration from `literal:` to `vault:` requires only updating the stored `api_key_ref` value in ConfigForge — no application code changes.

---

## ModelProfile Reference

All fields accepted in the `data` dict when registering an LLM config in ConfigForge, or in `profiles` when using inline config.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `provider` | str | Yes | `openai`, `google_genai`, `bedrock`, `google_vertexai` |
| `model` | str | Yes | Model ID (e.g. `gpt-4o`, `gemini-1.5-pro`) |
| `transport` | str | No | `direct` (default), `vertex`, `bedrock`, `gateway` |
| `temperature` | float | No | Default `0.1` |
| `max_tokens` | int | No | Maximum output tokens |
| `base_url` | str | No | Custom endpoint (OpenAI-compatible gateways) |
| `timeout_seconds` | float | No | Request timeout |
| `max_retries` | int | No | Retry count |
| `headers` | dict | No | Extra HTTP headers |
| `api_key_ref` | str | No | Secret ref for single-key auth (OpenAI, GenAI) |
| `secret_refs` | dict | No | Named secret refs for multi-credential auth (Bedrock explicit creds) |
| `api_key_env` | str | No | **Deprecated.** Use `api_key_ref: env:<VAR>` instead |
| `gcp_project` | str | No | GCP project ID (Vertex AI) |
| `gcp_location` | str | No | GCP region (Vertex AI) |
| `aws_region` | str | No | AWS region (Bedrock) |
| `aws_profile` | str | No | Named `~/.aws` profile (Bedrock) |

---

## Provider-Specific Notes

### OpenAI

```python
{
    "provider": "openai",
    "model": "gpt-4o",
    "api_key_ref": "env:OPENAI_API_KEY",
    "temperature": 0.1,
}
```

For Azure OpenAI or any OpenAI-compatible gateway, add `base_url`:

```python
{
    "provider": "openai",
    "model": "gpt-4o",
    "base_url": "https://your-gateway/v1",
    "api_key_ref": "env:GATEWAY_API_KEY",
}
```

### Google GenAI (Gemini)

```python
{
    "provider": "google_genai",
    "model": "gemini-1.5-pro",
    "api_key_ref": "env:GOOGLE_API_KEY",
    "temperature": 0.1,
}
```

Note: `max_tokens` maps to Gemini's `max_output_tokens` internally.

### AWS Bedrock

**Ambient IAM** (instance role, `AWS_*` env vars, or default profile):

```python
{
    "provider": "bedrock",
    "transport": "bedrock",
    "model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "aws_region": "us-east-1",
}
```

**Named profile:**

```python
{
    "provider": "bedrock",
    "transport": "bedrock",
    "model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "aws_region": "us-east-1",
    "aws_profile": "my-profile",
}
```

**Explicit credentials via `secret_refs`:**

```python
{
    "provider": "bedrock",
    "transport": "bedrock",
    "model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "aws_region": "us-east-1",
    "secret_refs": {
        "access_key": "env:AWS_ACCESS_KEY_ID",
        "secret_key": "env:AWS_SECRET_ACCESS_KEY",
    },
}
```

---

## Migration: Inline → ConfigForge

### Before (inline config in application code)

```python
from polyllm import LLMClient, PolyllmConfig

cfg = PolyllmConfig(
    default_profile="default",
    profiles={
        "default": {
            "provider": "openai",
            "model": "gpt-4o",
            "temperature": 0.1,
            "api_key_ref": "env:OPENAI_API_KEY",
        }
    },
)
client = LLMClient(cfg)
result = await client.chat(messages)
```

### After (config fetched from ConfigForge)

```python
from polyllm import RemoteConfigLoader

loader = RemoteConfigLoader()  # reads CONFIG_FORGE_URL from environment
client = await loader.load("prod.llm.openai.astra.primary")
result = await client.chat(messages)
```

**What changes:**
- Application code drops the `PolyllmConfig` construction entirely
- The `ModelProfile` lives in ConfigForge, registered once by ops/infra
- `CONFIG_FORGE_URL` must be set in the deployment environment
- Changing the model, provider, or key requires only a `PUT /config/{id}` to ConfigForge — no redeployment

**What stays the same:**
- The `chat()` call and `ChatResult` are identical
- Secret resolution still uses the same `SecretProvider` chain
- No LangChain dependency changes
