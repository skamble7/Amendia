# CC Prompt — Remap custom Amendia service host ports out of the 80xx band (+10000 → 18xxx)

**Read first:** `backend/deploy/docker-compose.yml`, `webui/vite.config.ts`, `webui/.env`, `backend/deploy/keycloak/amendia-dev-realm.json`.

## Why

On a corporate-managed Windows host, **McAfee Agent (`macmnsvc.exe`) binds `0.0.0.0:8081`** — the stub-exception-generator's default host port. Both Docker's port proxy and McAfee end up bound to 8081, so `localhost:8081` intermittently lands on McAfee, which accepts the TCP connection and sends nothing → `ERR_EMPTY_RESPONSE` (browser) / "empty reply" (curl) / "socket hang up" (Vite proxy). The app is healthy (its `/health` answers from inside the container); it's a **host port collision**, not a code/auth bug.

Fix: move the **nine custom Amendia services' host-published ports up by +10000** (into `18040–18090`), clearing the contended `80xx` band. **Keycloak (8087) and all third-party/infra (Mongo, Rabbit, ClickHouse, OTel) stay exactly as-is.** Container-internal ports do **not** change — only the host publish side and the Vite dev-proxy targets move.

## Port map (host side only; container/internal port unchanged)

| Service | host now | host new | container (unchanged) |
|---|---|---|---|
| config-forge | 8040 | 18040 | 8040 |
| stub-exception-generator | 8081 | 18081 | 8081 |
| ingestor | 8082 | 18082 | 8082 |
| agent-runtime | 8083 | 18083 | 8083 |
| process-registry | 8084 | 18084 | 8084 |
| webui | 8085 | 18085 | 8085 |
| identity | 8086 | 18086 | 8086 |
| notification-service | 8088 | 18088 | 8088 |
| glea-service | 8090 | 18090 | 8090 |

## Change EXACTLY these five things

1. **`backend/deploy/docker-compose.yml`** — the host side of the nine `ports:` mappings above, e.g. `- "8081:8081"` → `- "18081:8081"`. **Right side unchanged.**
2. **`webui/.env`** — the `VITE_*_URL` proxy targets → 18xxx: `VITE_STUB_URL=http://localhost:18081`, `VITE_INGESTOR_URL=http://localhost:18082`, `VITE_RUNTIME_URL=http://localhost:18083`, `VITE_REGISTRY_URL=http://localhost:18084`, `VITE_IDENTITY_URL=http://localhost:18086`. Also add (this file is missing them): `VITE_GLEA_URL=http://localhost:18090`, `VITE_NOTIFICATIONS_URL=http://localhost:18088`. **Leave `VITE_OIDC_ISSUER=http://localhost:8087/...` and all `VITE_*_BASE=/api/*` untouched.**
3. **`webui/.env.example`** — same `VITE_*_URL` updates (all seven) for parity.
4. **`webui/vite.config.ts`** — the `PROXY_TARGETS` fallback defaults → 18xxx (stub 18081, ingestor 18082, runtime 18083, registry 18084, identity 18086, notifications 18088, glea 18090). Leave the `test.env` `VITE_*_BASE` block alone.
5. **`backend/deploy/keycloak/amendia-dev-realm.json`** — replace the composed-webui origin `http://localhost:8085` → `http://localhost:18085` in `redirectUris`, `webOrigins`, and `post.logout.redirect.uris`. **KEEP every `http://localhost:5173` entry as-is** (that's the Vite dev origin and it does not change).

## DO NOT change (hard — these are internal or Keycloak/infra)

- Any **container-internal port** (right side of every `ports:` mapping).
- **Compose healthchecks** (`urllib.request.urlopen('http://localhost:8086/health')`, `…:8088…`, `…:8040/healthz`, `…:8090…`, `…:8084…`) — they execute **inside** the container against the container's own port. Changing them breaks health.
- **Service `config.py` defaults**: `STUB_BASE_URL`, `REGISTRY_BASE_URL`, `SELF_BASE_URL`, `CONFIG_FORGE_URL` (agent-runtime), `CONFIG_FORGE_URL` (process-registry), `identity_base_url` (amendia_auth), `SERVICE_BASE_URL` (stub) — internal / bare-metal contract, overridden by service-name env in Docker.
- **Internal service-name env URLs**: `http://stub-exception-generator:8081`, `http://identity:8086`, `http://keycloak:8080/...` (JWKS), `INGESTOR_STUB_BASE_URL`, `STUBEXC_SERVICE_BASE_URL`, etc.
- **Auth/OIDC**: every `*_AUTH_ISSUER`, `KC_HOSTNAME`, `VITE_OIDC_ISSUER` (Keycloak stays 8087).
- **Infra published ports**: Mongo 27017, Rabbit 5672/15672, ClickHouse 8123/9001, OTel 4317/4318.
- **Tests, READMEs, ADRs, `.env.example` `SERVICE_BASE_URL`, curl examples** — they reference internal/bare-metal ports; a doc pass can follow separately and is out of scope here.

## Acceptance / exit criteria

1. `docker compose -f backend/deploy/docker-compose.yml config` shows the nine host ports as 18xxx; all right-side (container) ports unchanged; healthchecks unchanged; Keycloak still 8087:8080.
2. After `docker compose up -d`, the host reaches each moved service on its new port: `curl http://localhost:18081/health`, `http://localhost:18086/health`, `http://localhost:18090/health` all answer.
3. `npm run dev` (still on 5173) proxies `/api/stub`, `/api/generators`, etc. to the 18xxx targets; the Exceptions page loads and the **Generate exception button enables**.
4. Login still works end-to-end (issuer + JWKS + 5173 redirect all unchanged). If the composed webui image is used, it is browsed at `localhost:18085` and its redirect resolves.
5. No internal / service-to-service URL changed; unit suites still green.

## Working agreement

Config-only — no application logic changes. **Do not `git add`/commit/push** — the operator commits. Avoid `git status`/`diff` via the device shell (stale `index.lock`).

**Operator pre-flight (Windows):** `netstat -ano | findstr "1804 1808 1809"` should return nothing before `docker compose up -d`.
