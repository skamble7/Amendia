# ADR-013 — Authentication frontend: webui PKCE sign-in, `/me`-driven identity, dev-switcher retirement & compat-bridge removal

- **Status:** Accepted (auth §6 step 2 — frontend)
- **Date:** 2026-07-08
- **Related:** `amendia_auth_architecture.md` (normative design — this ADR implements its §6 step 2 and §2.2);
  **ADR-012** (auth backend — the resource-server + identity service this consumes, and the compat bridge
  this removes); `backend/deploy/keycloak/README.md`; `Amendia_User_Guide.md` (formerly
  `webui/webui_user_guide.md`), `webui/README.md`.
- **Advances:** the "Frontend: webui PKCE integration, `/me`-driven identity, retire the user-switcher" item
  deferred by ADR-012; closes out the auth workstream (the platform is now strict by default).

## Context

ADR-012 made the backend a real OIDC resource server (validate bearer → `Principal` → identity service →
`AuthenticatedUser`), deleted the agent-runtime role-in-body stub, and enforced roles across services — but
left a **temporary compat bridge** (`*_AUTH_COMPAT_STUB`) so the pre-PKCE webui kept working: reads were
exempt without a bearer, and `claim`/`decide` still accepted a `{user_id, role}` body. The webui itself
still authenticated via a **dev user-switcher** — three hardcoded personas in a `SessionContext`, with the
selected `user_id`/`role` sent in request bodies.

This work replaces *who the user is* in the SPA with real OIDC (Authorization Code + PKCE), drives identity
from the identity service's `GET /me` (not token claims), and — because the browser now always sends a
bearer — **removes the compat bridge entirely**, leaving the whole platform strict by default. Governing
principle unchanged and now end-to-end: **authenticate with the IdP, authorize in Amendia**; the SPA reads
nothing but token expiry from the JWT — roles and identity come from `/me`.

## Decision

### Part A — OIDC client (PKCE)

`oidc-client-ts` + `react-oidc-context` (a generic certified OIDC library, not a vendor SDK — re-coupling
avoided). Config is **two env values** (`VITE_OIDC_ISSUER`, `VITE_OIDC_CLIENT_ID`); everything else comes
from discovery. `AuthProvider` at the app root: Auth Code + PKCE, `redirect_uri = origin + /auth/callback`,
scope `openid profile email`, `automaticSilentRenew` (the client has refresh-token rotation), tokens in
`sessionStorage`, RP-initiated logout via `signoutRedirect` (ends the Keycloak session, not just a local
wipe). A dedicated **`/auth/callback`** route completes the code exchange and restores the pre-login deep
link stashed in the OIDC `state`, so a link straight into a task survives the round-trip. The browser talks
to Keycloak (`:8087`) directly — it is deliberately **not** proxied; only `/api/*` (now including
`/api/identity → :8086`) is proxied by Vite/nginx.

### Part B — token-aware API client

The single `request()` fetch seam gains a module-level **auth bridge** (`src/auth/authToken.ts`) so the
non-hook client can reach the current access token, trigger a silent renew, and hand off on auth loss;
`AuthWiring` (inside the provider) wires it from `useAuth`. Every call carries `Authorization: Bearer`. A
**401** does one silent-renew + retry, then a full sign-in preserving location; **no token** fails closed to
sign-in rather than firing an unauthenticated request; a **403** is never a redirect — it is surfaced (the
runtime names the missing role or the SoD reason, rendered as the existing lock/toast states). The generated
API types were **regenerated** against the strict backend: `ClaimRequest` disappears (claim carries no
body), `DecideRequest` loses `user_id`, and a new `identity.ts` is emitted (`GET /me`). Every place that
sent identity in a body now sends nothing.

### Part C — `/me`-driven identity & route protection

`SessionContext` (hardcoded users) is replaced by an **`IdentityContext`** hydrated from `GET /me` via
TanStack Query (session-cached, refetch-on-focus) exposing `{amendiaUserId, displayName, email, roles,
hasRole}`. **Route protection** (`RequireAuth`) sequences the states: auth resolving → loader;
unauthenticated → sign-in (return path preserved); `/me` 403 `user_disabled` → a dedicated
account-disabled screen; `/me` pending → workspace loader; `/me` failed (non-auth) → retryable
identity-error screen. **Role-aware UI** (progressive disclosure, not security — the backend enforces): nav
hides Registry without `role.process.owner`; inbox/task SoD, claim ownership, and eligibility now key off
`amendia_user_id` + the `/me` roles (the old synthetic-id comparisons are swept out). The top bar shows the
`/me` name + roles; the menu's only action is **Sign out**.

### Part D — real sign-in screen

Screen 0's "**Continue with your organization**" button is now the only sign-in path — it starts the PKCE
redirect (in dev to Keycloak; in production to the customer's own IAM). The demo-user cards, the switcher,
`SessionContext`, and `session/users.ts` are deleted. The calm layout, tenant/environment tags, and the
session-ended state ("Your session ended — sign in to continue", wired to real expiry) are kept.

### Part E — compat-bridge removal (backend + compose)

Everything tagged for the frontend task is gone: the `compat_stub` setting in `amendia_auth`, its dependency
branches (`current_principal`/`current_user` now fail closed, never anonymous), the agent-runtime legacy
`{user_id, role}` body + `_resolve_actor`, the `*_AUTH_COMPAT_STUB` compose entries across all four services
+ identity, and the now-redundant `docker-compose.auth-strict.yml`. Backend suites stay green (compat-only
tests deleted with the code; test conftests moved to `auth_disabled=true`); the live integration test
(`test_e2e.py`) and `tools/demo_wire_repair.sh` mint real Keycloak bearers.

### Part F — realm audience fix (found during frontend verification)

The committed realm declared a custom `clientScopes: [amendia-api]` array. In Keycloak 26 that **replaces**
the built-in client scopes — dropping the `basic` scope, and with it the **`sub` claim** — so every token
was silently unusable (`/me` and every guarded call 401'd on "missing sub"). Fixed by moving the audience to
a **per-client `oidc-audience-mapper`** on both clients (an equivalent mechanism the design explicitly
allowed), leaving Keycloak's built-in default scopes intact (`sub`/`email`/`profile` all present).

## Consequences

- **Auth is real end-to-end, strict by default.** A deep link while signed out → sign-in → the org button →
  Keycloak login as `riya` → lands back on the deep link; the top bar shows her `/me` name and
  `ops_analyst` role. The full six-gate AC01 flow runs through the UI with real identities (sign out / in as
  `marcus` for approver gates); SoD keys off `usr-…` ids; **no request carries identity in a body**. Verified
  live: unauthenticated → 401, wrong role / SoD → 403, and `decided_by` on immutable records shows Amendia
  user ids.
- **Two env values swap the IdP.** `VITE_OIDC_ISSUER` + `VITE_OIDC_CLIENT_ID` point the SPA at Entra / Okta /
  any certified OIDC provider; nothing vendor-specific, no roles parsed from tokens. Mirrors the backend's
  IdP-agnosticism.
- **The whole compat surface is deleted** — `grep -r "TODO(auth-frontend)"` is empty. There is no longer any
  code path that reads a request-body identity.
- **Tests:** the webui suite mocks the auth context + `/me` at the boundary (MSW stays test-only) and adds
  targeted coverage — route-guard redirect, 401→renew→retry, 403 rendering (role + SoD), role-aware nav
  visibility, and callback deep-link restoration. `lint` / `test` / `build` green.
- **Deliberately deferred:** identity/role **admin screens** (assignment + enable/disable stay identity-API
  only), session-hardening policies (idle timeout), SCIM, claim-mapped roles, mTLS/service tokens, and the
  SSE/notification push (live surfaces still poll through `src/api/live.ts`).
- **Traps recorded for maintainers:**
  1. **Keycloak realm client scopes** — never hand-write a partial `clientScopes` array; it replaces the
     built-ins and drops `sub` (Part F). Use per-client mappers.
  2. **Admin console over HTTP** — the built-in `master` realm keeps `sslRequired: external` and rejects the
     admin console over plain HTTP through Docker's port mapping; relax it with `kcadm … update realms/master
     -s sslRequired=NONE` (re-run after a fresh recreate — dev H2 is ephemeral). The Amendia app never uses
     `master`. Documented in the Keycloak README.
  3. **Keycloak's browser login can't be faithfully emulated with curl** (session-cookie handling) — the real
     browser + `react-oidc-context` complete the flow; verification relied on a real login plus the demo
     script, not a scripted password POST.

## Addendum — 2026-07-09

The generated API client types (Part B) are now **drift-guarded**: `npm run gen:api:check`
(`webui/scripts/gen-api-check.mjs`) regenerates from the live services into a temp dir and fails on any
diff from the committed `src/api/gen/**`, and the generator now stamps an env-independent
`// GENERATED — DO NOT HAND-EDIT` banner (no host URL, so the check is byte-stable across machines). The
admin screens this ADR explicitly deferred landed in **ADR-014**; that ADR's addendum records the identity
type-regeneration closure (its `identity.ts` had been hand-extended while the stack was down, and is now
fully generator-owned).
