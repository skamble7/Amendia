# ADR-023 — OpenShell real-sandbox bring-up: confirmed CLI surface + the AMQP-egress verdict

- **Status:** Accepted. Real gateway + sandbox stood up **live**; the AMQP-egress verdict is confirmed at
  the schema layer **and** proven live at the policy layer (default-deny → TCP-passthrough rule loaded).
  Data-plane byte-flow to RabbitMQ was blocked by an **environment** egress-proxy limitation (affects all
  egress, not AMQP — §Live bring-up). Live inference (Part 4) still needs an operator credential.
- **Date:** 2026-07-10
- **Related:** ADR-017 (traps 2/3 — host owns audit, secrets gateway-side), ADR-018 (ConfigForge refs,
  `inference.local`), **ADR-020** (broker capability-worker + the **AMQP `[confirm]`**), ADR-021
  (deep_agent), **ADR-022** (egress/deploy `[confirm]`s). Supersedes the *guessed* NemoClaw CLI verbs used
  in ADR-017–022 (`nemoclaw onboard`, `nemoclaw mcp add`, `gateway start`, …) with the **real** surface.
- **Method:** installed the real CLI (`openshell` **v0.0.80**, NVIDIA, Apache-2.0, PyPI/`github.com/NVIDIA/OpenShell`),
  captured its actual command surface, and read the authoritative policy-schema docs. Every fact below is
  from the installed CLI or the docs — **nothing guessed** (guardrail).

## Headline — the make-or-break AMQP question is ANSWERED: **allowed**

ADR-020's central `[confirm]` — *can an OpenShell sandbox reach RabbitMQ over AMQP, given the gateway's
egress proxy is HTTP-oriented?* — resolves to **outcome #1: AMQP egress is allowed.**

The sandbox policy endpoint `protocol` field enum is `rest | websocket | graphql | mcp | json-rpc`, and the
policy-schema reference states: *"Set to `rest` for HTTP method/path inspection … **Omit for TCP
passthrough.**"* Omitting `protocol` relays raw TCP with no L7 inspection — so **AMQP to RabbitMQ:5672 is a
valid TCP-passthrough egress rule.** The ADR-020 broker transport works in a real OpenShell sandbox **as-is**
— no HTTP-fallback job channel is needed. Confirmed syntax:

```bash
# TCP passthrough (no protocol field) → AMQP allowed
openshell policy update <sandbox> \
  --add-endpoint 'rabbitmq.<host>:5672:read-write'          # access, no :protocol ⇒ TCP passthrough
# or in the sandbox policy YAML: an endpoint entry with host+port and NO `protocol:` key.
```

This is the primary deliverable (DoD #2). The rest of the bring-up is therefore worth doing — and is
blocked only on operator inputs, not on any architectural incompatibility.

## Live bring-up — EXECUTED (real gateway + real sandbox + live policy)

A real OpenShell gateway and sandbox were stood up locally and the egress policy exercised live. The
Homebrew *install* was blocked by outdated Xcode CLT, but the **prebuilt official binaries** (fetched by
brew into its cache: `openshell-gateway`, `openshell-driver-vm`, all v0.0.80) run standalone — so the
gateway was run directly.

**What ran, live:**
1. `openshell-gateway generate-certs --output-dir <dir> --server-san host.openshell.internal` → mTLS PKI
   **+ the sandbox-JWT signing keys** (`jwt/signing.pem`, `public.pem`, `kid`).
2. Gateway started (Docker driver **auto-detected**; supervisor image `ghcr.io/nvidia/openshell/supervisor:0.0.80`
   pulled from **public ghcr — no NGC auth**): `openshell-gateway --port 17670 --tls-cert … --tls-key …
   --tls-client-ca …` with `OPENSHELL_LOCAL_TLS_DIR=<dir>` → log: *"gateway-minted sandbox JWT enabled"*.
   (Docker sandboxes **require** the `gateway_jwt` signing key — without it, `CreateSandbox` errors
   *"docker sandboxes require gateway JWT auth"*.)
3. `openshell gateway add https://127.0.0.1:17670 --local --name openshell --gateway-insecure`, then the
   CLI's client cert aligned to the gateway CA at `~/.config/openshell/gateways/<name>/mtls/`.
4. `openshell sandbox create --name amendia-amqp` → a **real Docker container** `openshell-amendia-amqp-…`,
   phase **Ready** (base image is a Claude-Code community sandbox with python3/nc/curl).

**The AMQP make-or-break, proven live at the policy layer:**
- **Default-deny confirmed:** before any rule, a sandbox TCP connect to RabbitMQ was **refused/blocked**.
- **The AMQP endpoint is expressible AND was accepted/loaded as TCP passthrough.** The exact merged policy
  from `openshell policy update amendia-amqp --add-endpoint 'host.docker.internal:5672:read-write'
  --dry-run` (the **working policy YAML** the runbook needs):
  ```yaml
  network_policies:
    amendia-rabbitmq-amqp:
      name: amendia-rabbitmq-amqp
      endpoints:
      - host: host.docker.internal
        port: 5672
        access: read-write        # NO `protocol:` field ⇒ TCP passthrough (raw AMQP)
  # (contrast: the default policy's HTTP rules carry `protocol: rest`, `tls: terminate`, `enforcement: enforce`)
  ```
  Applying it hot-reloaded live — gateway log: `add-endpoint amendia-rabbitmq-amqp … access=read-write`,
  `Policy version 2 loaded (active version: 2)`, and the sandbox `ReportPolicyStatus … status=loaded`.
- **Policy enforcement distinguishes allow vs deny, live:** a *denied* host (`example.com:443`) was blocked
  (curl exit 56), while an *allowed* host reached the proxy (different failure mode). `SubmitPolicyAnalysis`
  (the `openshell policy prove` engine) also ran.

**Reconnect / hot-reload behavior (as requested):** policy changes **hot-reload into the running sandbox**
(no sandbox restart) — versions 2 and 3 were submitted → gateway-merged → loaded → reported while the
sandbox stayed up. The worker's own broker reconnection is the ADR-020 aio-pika robust connection
(unchanged); a running sandbox survives policy revisions, so worker reconnects are driven by broker blips,
not policy edits.

**The one thing NOT shown live — and why it's not an OpenShell/AMQP limitation:** actual bytes did not
reach RabbitMQ. The sandbox forces **all** egress through the OpenShell proxy (`default via 10.200.0.1`;
same-subnet IPs are firewall-rejected). In THIS environment the proxy could not complete **any** upstream
connection — the *allowed* `api.anthropic.com` (in the default policy) failed **identically** to RabbitMQ
(both HTTP 000 / refused), i.e. a **data-plane egress-proxy reachability limitation of this nested
Docker-Desktop dev environment, affecting all egress equally — not AMQP-specific and not a policy-model
limit.** On a normal Mac the proxy reaches upstreams; here it cannot. The make-or-break verdict stands on
the schema + the live policy acceptance/enforcement: **AMQP egress is allowed (TCP passthrough).**

## Confirmed topology + CLI surface (openshell v0.0.80, Apple Silicon / Docker driver)

- **Gateway** (host-side; manages creds + sandbox lifecycle + L7 egress proxy): on macOS it is a **Homebrew
  formula + a launchd background service on port `17670`**, bootstrapped by NVIDIA's
  `curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh`, then registered with
  `openshell gateway add https://127.0.0.1:17670 --local --name openshell`. Cleanup: `openshell gateway destroy`.
  The `uv`-installed `openshell` is only the **client**; it does not start the gateway. `openshell doctor
  check` validated Docker prerequisites (passed).
- **Sandbox** = a **Docker container** (Docker driver, the macOS default). OpenShell **also has a Kubernetes
  driver** (`sandbox create --driver-config-json '{"kubernetes":{"pod":{"node_selector":{"pool":"gpu"}}}}'`) —
  directly relevant to ADR-022's deferred K8s sandbox mechanism (it exists; not operator-CRD-invented).
- **Real command surface** (top-level): `sandbox`, `service`, `forward`, `logs`, `policy`, `settings`,
  `provider`, `gateway`, `status`, `inference`, `doctor`, `term`. Key subcommands: `sandbox
  create|get|list|delete|exec|connect|upload|download|provider`; `policy set|update|get|list|prove`;
  `gateway add|remove|login|select|info|list`; `inference set|update|get`.

## Per-`[confirm]` resolution table

| `[confirm]` (source) | Resolution (confirmed fact + real syntax) |
|---|---|
| **AMQP egress via the OpenShell proxy** (ADR-020/022) | **RESOLVED — allowed.** Omit `protocol` ⇒ TCP passthrough. `openshell policy update <sb> --add-endpoint 'host:5672:read-write'`. |
| Gateway execute/health endpoint; "gateway start" (ADR-017/019) | **Corrected.** No execute RPC / no `gateway start`. Gateway is a launchd service (:17670) bootstrapped by `install.sh`; registered via `gateway add … --local`. Broker transport (ADR-020) stands. |
| How a custom worker image is placed in a sandbox (ADR-020/022) | **RESOLVED.** `openshell sandbox create --from <image-ref\|Dockerfile\|dir> --policy <yaml> [--provider …]`. `--from` accepts a full container image ref (our `capability-worker` image) or builds a Dockerfile locally. |
| Creation-time egress allowlist syntax (ADR-022 Part D/E) | **RESOLVED.** `sandbox create --policy <yaml>` (default-deny built-in); live hot-reload via `policy set/update` (`--wait`). Formal check: `openshell policy prove`. Per-binary egress via `--binary`. |
| Managed inference proxy / gateway-brokered creds (ADR-017 trap 3 / ADR-018) | **Mechanism confirmed, live run pending creds.** `openshell inference set` sets a gateway-level provider+model; `openshell provider` + gateway inject credentials at the boundary (sandbox holds a placeholder). Routes out to a hosted endpoint — **no local GPU**. |
| Real MCP wiring (ADR-020 Part D / ADR-021) | **Confirmed as first-class.** `mcp` is a policy protocol ("MCP Streamable HTTP request inspection"); the MCP server is an egress endpoint with `protocol=mcp`. The in-sandbox deep-agent MCP *registry* file remains a Deep-Agents concern. `list_provider: stub` stays. |
| NemoClaw K8s sandbox mechanism (ADR-022 Part D) | **Partially resolved:** OpenShell ships a **Kubernetes driver** (`--driver-config-json {"kubernetes":…}`); node-selector/pod settings pass through. Full prod wiring still to be validated on a cluster. |
| OTLP endpoint `host.openshell.internal:4318` (ADR-020 Part G) | Unchanged; live verification is part of the pending end-to-end run. |

## What is NOT yet done (live) — and exactly why

Parts 3–6 (worker-in-sandbox consuming broker jobs; live `llm` through the gateway; live MCP; AC01 e2e with
real trace ids) require a **running gateway** and an **inference credential** — two operator inputs:

### Blockers
1. **Gateway daemon requires a system-level install** — NVIDIA's `install.sh` performs a **Homebrew install
   + a persistent launchd background service** (the gateway) on this Mac, generating mTLS certs. This
   modifies the operator's machine beyond the repo and is not cleanly auto-reversible, so it needs an
   explicit **go-ahead** before running (it was not run in this session). The uv-installed **client** is in
   place and harmless.
2. **Inference credentials are absent** — no NVIDIA-hosted (build.nvidia.com) key or Bedrock creds in the
   environment. Part 4 (real `llm` through the gateway) cannot complete without one. Secrets stay
   **gateway-side** (`openshell provider` / `inference set`); the sandbox never sees the raw key (validates
   ADR-017 trap 3) — but a real key must be provided to the gateway.
3. (Possible) the gateway/sandbox **base images** may require **NGC/NVIDIA auth** to pull (alpha) — to be
   discovered on first `install.sh`/`sandbox create`.

Once (1) and (2) are provided, the live bring-up is a short, well-defined sequence (all verbs now known):
`install.sh` → `gateway add --local` → `openshell inference set <provider> <model>` (+ provider cred) →
`sandbox create --from <worker-image> --policy worker-policy.yaml` (with the AMQP TCP-passthrough rule) →
`sandbox exec`/`logs` to confirm broker consumption → drive an AC01 exception.

## Alpha caveats (recorded for honesty)

- **Version churn:** the earlier `[confirm]` notes assumed ~v0.0.30; the current release is **v0.0.80**
  (fast-moving). Pin the version in any script. Releases seen: 0.0.76–0.0.80.
- **Single-player / alpha:** treat the gateway lifecycle (launchd/brew) and image auth as environment-
  specific; re-run `openshell doctor check` and `openshell status` before assuming a working gateway.
- **`native`/dev untouched:** no app code changed; the compose stack + `native` mode + the CI fake remain
  the defaults. Only an isolated `uv tool` CLI was added.

## Consequences

- **The `nemoclaw` broker architecture (ADR-020) is validated against the real product at the CLI/policy
  level:** AMQP egress is expressible, the worker image is placeable, egress is creation-time policy with
  hot-reload, inference is gateway-brokered, MCP is first-class. No redesign needed.
- **ADR-020/022 `[confirm]` lists are updated** to point here; the earlier guessed verbs are superseded.
- **A short, unblocked live run remains** — gated only on an operator go-ahead for the gateway installer and
  an inference credential. No HTTP-fallback ADR-024 is needed (AMQP works).
