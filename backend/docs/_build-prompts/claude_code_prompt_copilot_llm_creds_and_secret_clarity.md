# Claude Code prompt — unblock copilot onboarding (LLM creds) + fix the misleading secret-resolution error

Two related fixes. This is a **config + DX** change, not a feature; it is **not** related to ADR-059/060/061 —
do not touch those.

## Root cause (confirmed, do not re-investigate)

`POST /onboarding/copilot/generate` 500s because the onboarding copilot has no usable LLM credentials. The
`REGISTRY_COPILOT_LLM_CONFIG_REF` compose var (`dev.llm.bedrock.explicit-creds`) is only the **config-forge key**;
the actual model profile is **defined in config-forge's seed** (`config-forge-service/scripts/seed.py`, the
`explicit-creds` entry) as a Bedrock profile whose secret refs are `env:AWS_ACCESS_KEY_ID` /
`env:AWS_SECRET_ACCESS_KEY` — deliberately `env:*` so "no real secrets are stored here" (the seed's own words).
config-forge returns that profile fine (the resolve is 200), but those env vars are **unset** in the container. polyllm's
`CompositeSecretProvider(Literal, Env, File)` resolves `env:AWS_ACCESS_KEY_ID` as: Env → `os.getenv(...)` →
`None` (unset) → next → File → raises `ValueError("FileSecretProvider only supports file:* refs")`; the composite
re-raises that **last** exception — so the File message masks the real cause ("the AWS env var isn't set").
Compose never declared the AWS vars, and `agent-runtime` (`AGENTRT_LLM_CONFIG_REF`) hits the same wall at run time.

## Part 1 — Wire the AWS credential passthrough (config; the primary unblock)

Assumption: the operator has AWS Bedrock creds. (If not, see the "Alternative" note below — do not implement it
unless told to.)

1. In `backend/deploy/docker-compose.yml`, add to the `environment:` block of **both** `process-registry` and
   `agent-runtime` (sourced from the host/`.env`, **never** hardcoded):
   ```yaml
         AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID}
         AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY}
         AWS_SESSION_TOKEN: ${AWS_SESSION_TOKEN:-}
         AWS_REGION: ${AWS_REGION:-us-east-1}
   ```
   `EnvSecretProvider` reads `os.getenv`, so this is all polyllm needs. Include `AWS_SESSION_TOKEN` (optional,
   for temporary creds); it defaults empty and is harmless when unused.
   Note: the config-forge seed intentionally keeps secrets OUT of config-forge (`env:*` refs), so the env
   passthrough is the *intended* credential mechanism here — do not move the creds into config-forge as
   `literal:` unless the operator asks. Also: config-forge is **manually seeded** (see the commented
   `docker compose run --rm config-forge python scripts/seed.py …` in the compose file) and `down -v` wipes it —
   so after a reset the operator must both re-seed config-forge AND have the AWS env vars present. Add a short
   note to this effect in the report so the reset ritual is captured.
2. Add `backend/deploy/.env.example` documenting the required vars (names only, **no real values**):
   ```
   AWS_ACCESS_KEY_ID=
   AWS_SECRET_ACCESS_KEY=
   AWS_SESSION_TOKEN=
   AWS_REGION=us-east-1
   ```
   Compose auto-loads `backend/deploy/.env` for `${...}` substitution. Ensure `.gitignore` ignores
   `backend/deploy/.env` (and any `.env`) so real creds are never committed — add the rule if missing. Do NOT
   create a real `.env` (the operator supplies it).
3. Do not change `REGISTRY_COPILOT_LLM_CONFIG_REF` / `AGENTRT_LLM_CONFIG_REF` (stay on Bedrock).

**Alternative (only if the operator says they lack AWS creds — do not do by default):** repoint
`REGISTRY_COPILOT_LLM_CONFIG_REF` and `AGENTRT_LLM_CONFIG_REF` to another config-forge key defined in
`config-forge-service/scripts/seed.py` (e.g. an OpenAI/`google_genai`/`nemoclaw` dev profile), and wire that
profile's `env:` var(s) (e.g. `OPENAI_API_KEY`) the same passthrough way. Flag in the report which provider was
chosen if this path is taken.

Read-first for Part 1: `config-forge-service/scripts/seed.py` (the `explicit-creds` Bedrock entry — the source of
the `env:AWS_*` refs), the `process-registry` + `agent-runtime` `environment:` blocks in
`backend/deploy/docker-compose.yml`, and the existing `.gitignore`.

## Part 2 — Make the secret-resolution failure legible (polyllm DX bug)

`libs/polyllm/src/polyllm/secrets.py` — `CompositeSecretProvider.get` must not surface a **scheme-mismatch** from
a non-matching provider as the representative error. Fix so:

4. The composite dispatches by the ref's scheme (`_split_ref(ref)`) to the provider(s) that handle it — a
   provider whose scheme doesn't match is **skipped**, not treated as the failure (either dispatch to the matching
   provider only, or have providers return a "not my scheme" sentinel/`None` instead of raising; pick the cleaner
   one and keep direct-use semantics sane).
5. When no provider resolves the ref, raise a **clear** error naming the ref and the actual reason — e.g.
   `"could not resolve secret ref 'env:AWS_ACCESS_KEY_ID' — environment variable 'AWS_ACCESS_KEY_ID' is not set"`
   for the env case, and an analogous clear message for an unknown scheme. The `FileSecretProvider` "only supports
   file:*" text must never be what surfaces for an `env:` ref.
6. Unit tests in polyllm: (a) `env:X` with the var unset → the clear "env var not set" error (assert the ref/var
   name is in the message; assert the File message is NOT); (b) `literal:`, `env:` (set), `file:` each still
   resolve correctly through the composite; (c) an unknown scheme → a clear unknown-scheme error.

## Part 2b — Surface it cleanly from the copilot (no raw 500)

7. In `process-registry/app/services/copilot/llm.py` (`_call_structured` / around `client.chat(...)`), catch a
   credential/LLM resolution failure and raise the existing `CopilotLLMError` (or equivalent) with the clear
   reason, and ensure the `POST /onboarding/copilot/generate` route maps it to a clean 4xx/503 with that message —
   not an unhandled 500 ASGI traceback. The operator should see "copilot LLM unavailable: AWS_ACCESS_KEY_ID not
   set" in the response, not a stack trace.

## Do not

- Never hardcode or commit real AWS keys or any secret. Only `${VAR}` references + `.env.example` (empty).
- Do not implement the repoint alternative unless explicitly told the operator lacks AWS creds.
- Do not touch ADR-059/060/061 code, HITL gating, or the type-compat guard.
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- With real creds in `backend/deploy/.env` and `docker compose up -d --force-recreate process-registry
  agent-runtime`, `POST /onboarding/copilot/generate` succeeds (copilot returns a proposal); confirm
  `docker exec deploy-process-registry-1 printenv AWS_ACCESS_KEY_ID` is set.
- With the AWS vars **unset**, the failure is a **clear** error naming the missing env var/ref — both in polyllm's
  raised error and in the copilot-generate HTTP response (a clean 4xx/503, no 500 traceback). The
  `FileSecretProvider` message no longer appears.
- polyllm unit tests (Part 2) green; `pytest` green for `polyllm` and `process-registry`.
- `.gitignore` covers `backend/deploy/.env`; `.env.example` present with empty values; no secret committed.

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_copilot_llm_creds_and_secret_clarity_report.md`
(uncommitted): (1) outcome one-liner; (2) the compose passthrough (both services) + `.env.example`/`.gitignore`;
(3) the polyllm composite fix + the new error message + tests; (4) the copilot clean-error surfacing; (5)
verification — commands + results (creds-set success, creds-unset clear-error, `pytest`); (6) anything left open
(e.g. whether the operator needs to supply creds). Keep it to a screen.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. Never commit secrets. Stay inside the Amendia repo and
the scope above.
