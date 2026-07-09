# Amendia webui

Operator UI for the Amendia agentic payment-exception platform — sign-in, task inbox with the four
HITL decision modes, instance and exception views, dashboard, and the process registry with an
onboarding wizard. React 18 + TypeScript (strict) + Vite + Tailwind + shadcn-style primitives,
TanStack Query, React Router, react-hook-form + zod.

**Live backend only.** Every piece of data on screen comes from the running services — there is no
mock mode. The app requires the compose stack.

## Quickstart

```bash
# 1. start the backend (from the repo root)
docker compose -f backend/deploy/docker-compose.yml up -d

# 2. run the UI
cd webui
pnpm install        # first time only
cp .env.example .env
pnpm dev
```

Then, in the app:

1. Open http://localhost:5173 and **sign in** as a development user (see below).
2. Go to **Exceptions** → **Generate exception (via stub source)** (`AC01`).
3. The exception appears, an instance starts, and its gates show up in the **Task inbox** — work them.

The dev server proxies `/api/*` to the services (`:8081`–`:8084`, plus identity `:8086`), so the app is
single-origin. Keycloak (`:8087`) is **not** proxied — the browser talks to it directly for the redirect
flow and silent renew. The built image serves the same app via nginx on **:8085** (the `webui` compose
service).

## Sign-in (OIDC / PKCE)

Sign-in is real **OIDC (Authorization Code + PKCE)** via `oidc-client-ts` + `react-oidc-context`. The
"Continue with your organization" button redirects to the IdP; in dev that's the bundled Keycloak. Sign
in as a dev user — `riya` (analyst), `marcus` (approver), or `priya` (process owner + platform admin) —
password `dev-password` (dev only; see `backend/deploy/keycloak/README.md`). Identity and roles shown in
the app come from the identity service's `GET /me`, never parsed from the token.

**Switching personas = sign out, sign in as the other user.** There is no user switcher (that was the old
placeholder). Separation of duties requires, e.g., that the analyst who drafts a repair is not the person
who approves it — so sign out as `riya` and back in as `marcus` for the approver gates. The full operator
narrative is in [`webui_user_guide.md`](./webui_user_guide.md).

Auth reads from env only (`.env`): `VITE_OIDC_ISSUER`, `VITE_OIDC_CLIENT_ID`, plus the
`VITE_IDENTITY_BASE` / `VITE_IDENTITY_URL` proxy targets. In production the two OIDC values point at the
customer's own IdP — no code change. The token is attached as `Authorization: Bearer` to every API call;
a 401 triggers one silent renew + retry, then a full sign-in; a 403 is surfaced (missing role / SoD),
never a redirect.

## Generate exception

The **Generate exception (via stub source)** button (Exceptions screen, always visible) calls the real
`stub_exception_generator`, which persists to Mongo and publishes real events — the legitimate way to
create data in this environment. Pick a reason code (`AC01` / `AC04` / `RC01` / `BE04`).

## Backend unreachable

If a service can't be reached (stack stopped), the affected screen shows a clear inline banner —
"<service> is unreachable — is the backend stack running?" with the compose command — instead of an
empty-but-healthy-looking table. Detection is centralized in the API client (`src/api/client.ts`,
`isConnectivityError`); the treatment is `src/components/ConnectivityState.tsx`.

## Troubleshooting auth

- **The sign-in button errors / redirect fails** — Keycloak (`:8087`) isn't running. This is distinct
  from the "service unreachable" banner (which is about `:8081`–`:8086`): the sign-in redirect happens
  before any API call. Start the stack (`docker compose … up`) and retry.
- **Signed in, but every request 401s / you bounce to sign-in** — usually **clock skew**: the browser's
  clock is far enough off that the token's `iat`/`exp` fail validation. Fix the machine clock (or Docker
  VM clock). Also check `VITE_OIDC_ISSUER` matches the realm issuer exactly.
- **`aud`/`iss` rejected right after login** — the token audience/issuer doesn't match what the services
  expect; see the dev-networking note in `backend/deploy/keycloak/README.md`.

## Types from OpenAPI

API types are **generated**, never hand-written. With the stack up:

```bash
pnpm gen:api        # writes src/api/gen/{stub,ingestor,runtime,registry,identity}.ts (committed)
```

The two agent-runtime instance-detail endpoints (`GET /instances/{id}` and `/state`) have no FastAPI
`response_model`, so their shapes are hand-written in `src/api/types.ts` (`InstanceDetail` /
`InstanceState`) — keep them in sync with `agent-runtime/app/routers/instances.py`.

## Scripts

| Script | What |
|---|---|
| `pnpm dev` | Vite dev server (proxies to the live services) |
| `pnpm build` | Typecheck + production build |
| `pnpm lint` | eslint + typescript-eslint |
| `pnpm test` | vitest + testing-library (MSW is a test-only dependency) |
| `pnpm gen:api` | Regenerate OpenAPI types (stack must be up) |

## Registry & onboarding

The **Registry** screens read the live catalog (the seeded `wire-repair-standard` pack, its
capabilities, and artifact schemas come from the registry's onboarding pipeline on a fresh stack).
**Registry → Onboard pack** walks Manifest → BPMN → **Validate** → **Activate** against the real
registry endpoints; the validation report is grouped by the 7 validator stages with severity chips and
element ids. Activation is blocked while any stage reports an error.

## Delivery

Multi-stage `Dockerfile` builds the SPA and serves it via nginx on **:8085**, proxying `/api/<service>`
to the backends (single-origin). The `webui` service is wired into
`../backend/deploy/docker-compose.yml`. The four FastAPI services carry a dev-only `*_ENABLE_DEV_CORS`
flag (default on in compose) so a separately-served build can call them directly.

## Design source of truth & known deltas

The visual source of truth is the Claude Design prototype **Amendia.dc.html**. This build uses a
CSS-variable token system (`src/index.css`) mapping the design's semantic colors (agent=purple,
artifact=teal, attention=amber, process=coral, plus status green/red); reconcile token *values* and
screen layouts against the seeded prototype in one pass — components read tokens, not hard-coded colors.

Design ↔ contract deltas honored (contracts win on data/behavior):

- The pack's BPMN diagram shows a parallel fork/join, but the executed pack is **linearized** — the step
  tracker is a linear chain derived from binding/actor order.
- `sod.derived_from` carries human-readable reason strings at runtime (rendered verbatim in the SoD lock
  tooltip).

## Out of scope (seams left ready)

Identity/role **admin screens** (role assignment + user enable/disable are identity-service API only),
session-hardening policies (idle timeout), SSE/notification-service (all live behavior polls through
`src/api/live.ts` — swap the interval for an EventSource there), Playwright e2e.
