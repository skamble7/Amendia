# ConfigForge

**Platform Config Registry Service** — the authoritative store for named, typed configuration records used across the platform ecosystem.

ConfigForge decouples platform services and tools from the raw details of their configurations (LLM provider settings, API keys, model parameters, etc.). Platforms register configs once; their code carries only a short canonical reference string.

---

## Contents

1. [Overview](#overview)
2. [Canonical Reference Format](#canonical-reference-format)
3. [API Reference](#api-reference)
4. [Config Kinds](#config-kinds)
5. [Secret Storage Patterns](#secret-storage-patterns)
6. [Running the Service](#running-the-service)
7. [Seeding Default Configs](#seeding-default-configs)
8. [Adopting ConfigForge in a Platform](#adopting-configforge-in-a-platform)

---

## Overview

| Property | Value |
|----------|-------|
| Port | **8040** |
| Database | MongoDB (`ConfigForge` database) |
| Health | `GET /healthz` |
| API docs | `GET /docs` |

### Problem it solves

Without ConfigForge, every platform service that uses an LLM must construct a `PolyllmConfig` object inline — embedding provider choice, model IDs, temperature, and API key references directly in application code or per-service environment files. Changing a model requires a redeployment. Sharing a config across platforms means duplicating it.

ConfigForge provides a single place to register, update, and look up configs by name. Platforms carry only a canonical reference string like `prod.llm.openai.astra.primary`, resolve it at runtime, and never need to know the underlying provider details.

---

## Canonical Reference Format

Every config entry has a `ref` field — a dot-separated string computed from its structured fields at creation time and stored with a unique index.

```
{env}.{kind}[.{provider}][.{platform}].{name}
```

| Segment | Required | Values | Purpose |
|---------|----------|--------|---------|
| `env` | Yes | `prod`, `dev`, `staging`, `global` | Deployment environment. Use `global` for configs shared across all envs. |
| `kind` | Yes | `llm`, `storage` | Config category |
| `provider` | Optional | `openai`, `anthropic`, `bedrock`, `google_genai` | Vendor/service. Omit for kind-level configs not tied to a specific provider. |
| `platform` | Optional | `raina`, `zeta`, `orko`, `astra` | Platform that owns this config. Omit for shared/infra configs. |
| `name` | Yes | `default`, `primary`, `fast` | Short disambiguator |

### Examples

| Ref | Meaning |
|-----|---------|
| `prod.llm.openai.default` | Shared default OpenAI config for production |
| `prod.llm.openai.astra.primary` | ASTRA's primary OpenAI config in production |
| `dev.llm.google_genai.default` | Shared Gemini config for development |
| `prod.llm.bedrock.zeta.modernization` | Zeta's Bedrock config for modernization workloads |
| `global.llm.openai.default` | OpenAI config shared across all environments |

### Key property: computed, not parsed

The `ref` is **computed server-side at creation** from the structured fields and stored directly. Lookups are a single indexed query — `GET /config/resolve/{ref}`. Nothing parses the string at runtime.

---

## API Reference

Base path: `http://config-forge-service:8040`

### Create a config entry

```
POST /config/
```

**Body:**

```json
{
  "env": "prod",
  "kind": "llm",
  "provider": "openai",
  "platform": "astra",
  "name": "primary",
  "description": "ASTRA's primary GPT-4o config in production",
  "data": {
    "provider": "openai",
    "model": "gpt-4o",
    "temperature": 0.1,
    "api_key_ref": "env:OPENAI_API_KEY"
  },
  "created_by": "ops"
}
```

**Response `201`:**

```json
{
  "id": "a3f9...",
  "ref": "prod.llm.openai.astra.primary",
  "env": "prod",
  "kind": "llm",
  "provider": "openai",
  "platform": "astra",
  "name": "primary",
  "description": "ASTRA's primary GPT-4o config in production",
  "data": { ... },
  "created_by": "ops",
  "created_at": "2026-03-08T10:00:00Z",
  "updated_at": "2026-03-08T10:00:00Z"
}
```

Returns `409 Conflict` if a config with the same ref already exists.

---

### Resolve by canonical ref *(primary polyllm lookup)*

```
GET /config/resolve/{ref}
```

```bash
GET /config/resolve/prod.llm.openai.astra.primary
```

This is the endpoint polyllm's `RemoteConfigLoader` calls internally. It returns the full entry including `data`, which is used to build the `ModelProfile`.

---

### List configs

```
GET /config/?env=prod&kind=llm&provider=openai&platform=astra
```

All query params are optional filters. Returns all entries when no filters are applied.

---

### Get by ID

```
GET /config/{id}
```

---

### Update a config

```
PUT /config/{id}
```

Only `description` and `data` can be updated. The `ref` and its component fields (`env`, `kind`, `provider`, `platform`, `name`) are immutable after creation — create a new entry if you need to change them.

```json
{
  "data": {
    "provider": "openai",
    "model": "gpt-4o-2024-11-20",
    "temperature": 0.05,
    "api_key_ref": "env:OPENAI_API_KEY"
  }
}
```

---

### Delete a config

```
DELETE /config/{id}
```

---

## Config Kinds

### `llm`

The `data` field must contain a valid `ModelProfile`-compatible dict. See the [polyllm README](../../../platform-libraries/libs/polyllm/README.md) for the full field reference.

**Minimum required fields:**

```json
{
  "provider": "openai",
  "model": "gpt-4o"
}
```

**Full example (OpenAI):**

```json
{
  "provider": "openai",
  "model": "gpt-4o",
  "temperature": 0.1,
  "max_tokens": 8192,
  "timeout_seconds": 60,
  "max_retries": 3,
  "api_key_ref": "env:OPENAI_API_KEY"
}
```

**Full example (Bedrock with explicit creds):**

```json
{
  "provider": "bedrock",
  "transport": "bedrock",
  "model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
  "temperature": 0.1,
  "aws_region": "us-east-1",
  "secret_refs": {
    "access_key": "env:AWS_ACCESS_KEY_ID",
    "secret_key": "env:AWS_SECRET_ACCESS_KEY"
  }
}
```

---

## Secret Storage Patterns

The `data` field stores secret *references*, not raw values. These references are resolved by polyllm's `SecretProvider` chain at call time.

| Pattern | `api_key_ref` value | When to use |
|---------|---------------------|-------------|
| Env var (deployment-managed) | `env:OPENAI_API_KEY` | Key is injected by the deployment environment (Docker, K8s, CI) |
| Inline in ConfigForge | `literal:sk-abc123...` | Key stored directly in ConfigForge; no external secret store needed |
| File on disk | `file:/run/secrets/keys.json#openai` | Key mounted as a Docker secret or file |
| Vault *(planned)* | `vault:secret/llm/openai#api_key` | Key managed in HashiCorp Vault |

**Migration path:** Start with `literal:` for simplicity. When you introduce Vault, update the `api_key_ref` value in ConfigForge via `PUT /config/{id}` — no platform code changes required.

---

## Running the Service

### Locally (without Docker)

```bash
cd services/config-forge-service
pip install -e ".[dev]"

# Needs a running MongoDB on localhost:27017
uvicorn app.main:app --host 0.0.0.0 --port 8040 --reload
```

### With Docker Compose

```bash
docker compose -f deploy/docker-compose.yml up -d mongodb config-forge-service
```

The service is available at `http://localhost:8040`. API docs at `http://localhost:8040/docs`.

---

## Seeding Default Configs

The seed script pre-populates ConfigForge with template LLM configs for all active polyllm providers. It is idempotent — safe to run multiple times.

```bash
cd services/config-forge-service

# Preview what would be created
python scripts/seed.py --env dev --dry-run

# Seed dev environment (against dockerized MongoDB)
python scripts/seed.py --env dev

# Seed prod
python scripts/seed.py --env prod --mongo-uri mongodb://mongodb:27017 --db ConfigForge
```

**Seeded refs** (for `env=dev`):

| Ref | Provider | Model |
|-----|----------|-------|
| `dev.llm.openai.default` | OpenAI | gpt-4o |
| `dev.llm.openai.fast` | OpenAI | gpt-4o-mini |
| `dev.llm.openai.reasoning` | OpenAI | o3 |
| `dev.llm.openai.gateway` | OpenAI-compatible gateway | gpt-4o |
| `dev.llm.google_genai.default` | Google Gemini | gemini-1.5-pro |
| `dev.llm.google_genai.flash` | Google Gemini | gemini-1.5-flash |
| `dev.llm.bedrock.default` | AWS Bedrock | claude-3.5-sonnet (ambient IAM) |
| `dev.llm.bedrock.named-profile` | AWS Bedrock | claude-3.5-sonnet (named profile) |
| `dev.llm.bedrock.explicit-creds` | AWS Bedrock | claude-3.5-sonnet (explicit keys) |
| `dev.llm.google_vertexai.default` | Google Vertex AI | gemini-1.5-pro *(placeholder)* |

These are templates using `env:*` refs. Update the `data.api_key_ref` field with `PUT /config/{id}` to switch to `literal:` or `vault:` for stored keys.

---

## Adopting ConfigForge in a Platform

### 1. Register a config (one-time, by ops/infra)

```bash
curl -X POST http://localhost:8040/config/ \
  -H "Content-Type: application/json" \
  -d '{
    "env": "prod",
    "kind": "llm",
    "provider": "openai",
    "platform": "astra",
    "name": "primary",
    "description": "ASTRA primary LLM config",
    "data": {
      "provider": "openai",
      "model": "gpt-4o",
      "temperature": 0.1,
      "api_key_ref": "literal:sk-your-key-here"
    }
  }'
# → ref: "prod.llm.openai.astra.primary"
```

### 2. Use in platform code

```python
from polyllm import RemoteConfigLoader

# Initialise once (e.g. at app startup or as a dependency)
loader = RemoteConfigLoader(
    base_url=settings.CONFIG_FORGE_URL,  # e.g. "http://config-forge-service:8040"
)

# Per request / capability
client = await loader.load("prod.llm.openai.astra.primary")
result = await client.chat(messages)
```

### 3. Add `CONFIG_FORGE_URL` to service settings

```python
# app/config.py
class Settings(BaseSettings):
    CONFIG_FORGE_URL: str = "http://config-forge-service:8040"
    LLM_CONFIG_REF: str = "prod.llm.openai.astra.primary"
    ...
```

### 4. Add to `.env.example`

```
CONFIG_FORGE_URL=http://config-forge-service:8040
LLM_CONFIG_REF=prod.llm.openai.astra.primary
```

### 5. Add polyllm[remote] dependency

```toml
# pyproject.toml
dependencies = [
  ...
  "polyllm[langchain,remote]",
]
```

### What to remove

Once migrated, the platform no longer needs:
- Any inline `PolyllmConfig(...)` construction
- `OPENAI_API_KEY` (or any provider key) in its own environment
- Per-service model/provider configuration
