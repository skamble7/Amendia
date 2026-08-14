# Corpus smoke tests — one command, green/red per worked-example

A **manually-launchable** full-stack, happy-path smoke over the worked-example corpus
(`backend/docs/methodology/worked-examples/`). After a major change, run one command and get a **PASS/FAIL per
domain** instead of hand-driving a scenario. It generalizes `tools/demo_wire_repair.sh` (token → fire trigger →
poll ingestor → drive HITL gates → assert terminal outcome) into a **data-driven** suite: one small YAML spec
per domain drives a shared harness, so **adding a worked-example is a new spec file, not new test code**.

`pytest` + `httpx` + `pyyaml` only (free/OSS). This is test scaffolding — it does **not** deploy or onboard.

## Launch

```bash
# 1. bring the stack up and ONBOARD the three domains (wire is seeded; ACH + restaurant are onboarded in the wizard)
docker compose -f backend/deploy/docker-compose.yml up -d
docker compose -f pega_stub/deploy/docker-compose.yml up -d        # ACH's mock Pega orchestrator

# 2. deps + run
pip install -r backend/tests/smoke/requirements.txt
bash tools/smoke.sh                 # all domains, prints a per-domain PASS/FAIL summary
bash tools/smoke.sh -k ach          # one domain (pass-through pytest args)
# or directly:
pytest -m smoke -v backend/tests/smoke
```

## What "green" proves

For each domain the suite fires the **real** trigger and asserts the case reaches its expected terminal state:
- **wire_transfer** — a `wire-repair-standard` exception (reason `AC01`) runs through its HITL gates to
  `instance = completed`.
- **ach_exposure** — the mock Pega `credit_approve` case drives 3 Amendia segments (approve gate on B) and the
  **cohort** `ach_exposure_cohort` reaches `state = closed`, `outcome = Released`, no failed members.
- **restaurant** — a `dine_in` ticket runs its dining gates to `instance = completed`.

## Degrading (skip, don't error)

- **Stack down** → the whole suite **skips** with `stack not reachable (… down)`.
- **A pack not onboarded** → that domain **skips** with `onboard <pack_key> first`; the others still run.
- **A persona not in the realm** → that domain **skips** with guidance to seed it or edit the spec.
Only a stack that is up + onboarded but produces the wrong terminal state is a **failure**.

## Env overrides (compose host-port defaults)

`INGESTOR` (`:18082`), `RUNTIME` (`:18083`), `REGISTRY` (`:18084`), `GLEA` (`:18090`), `STUB` (`:18081`),
`PEGA_STUB` (`:9095`), `NOTIFICATION` (`:18088`), `IDENTITY` (`:18086`), `KEYCLOAK` (`:8087`), `REALM`
(`amendia-dev`), `CLI_CLIENT`/`CLI_SECRET`/`DEV_PASSWORD`. See `config.py`.

## Add a domain (no code change)

Drop `scenarios/<domain>.yaml`:

```yaml
domain: my_domain
pack_keys: [my-pack]                    # preflight: must be active in the registry
trigger:
  kind: stub_generator                  # pega_stub | stub_generator | direct_trigger
  request: { generator: wire, body: { reason_code: AC01 } }
correlation: trigger_id                 # where to read the case handle from the fire result
hitl:
  default_persona: riya
  roles: { "role.payments.ops_approver": marcus }   # role id -> persona
  personas: [riya, marcus]              # SoD fallback pool
expect:
  instance_status: completed
  cohort: { state: closed, outcome: Released }       # omit for a non-cohort (single-instance) domain
timeout_s: 150
# skip: true / skip_reason: "…"         # ship-but-don't-run a domain that isn't runnable as-is
```

The harness picks the driver by `trigger.kind`, resolves HITL gates by the task's role (SoD-aware), and asserts
the single instance **or** the cohort per `expect`. A genuinely new trigger mechanism is a new entry in
`drivers.py` `DRIVERS`; everything else is just the spec.

## Layout

`config.py` (endpoints from env) · `client.py` (readiness, token mint/cache, `/me`, poll) · `scenarios.py`
(YAML → `Scenario`) · `drivers.py` (trigger-driver registry) · `hitl.py` (persona/SoD-aware resolve loop) ·
`conftest.py` (session fixtures + readiness skip) · `test_smoke.py` (the one parametrized test).

## Not this task (follow-ups)

Self-contained onboarding tier (`POST /packs` with committed manifests, no wizard/LLM) · branch + SLA-breach
variants (e.g. ACH `late_closeout`) · CI wiring. The copilot/LLM onboarding path is deliberately **not** used
(non-deterministic) — the smoke runs against an already-onboarded stack.
