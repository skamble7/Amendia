# Amendia Authentication & Authorization — Architecture

**Status:** design accepted, pre-implementation.
**Deployment model assumption:** Amendia is deployed into each customer's infrastructure — **one deployment, one bank, one IdP**. No multi-bank tenancy on a shared instance. There is no `tenant` field on events or records — single-tenant is the deployment boundary, not a data attribute.
**Diagrams:** `diagrams/auth-components.svg`, `diagrams/auth-flows.svg` (self-contained, dark-mode aware).

---

## 1. Governing principle

**Authenticate with their IAM; authorize in Amendia.**

The customer's identity provider (Entra ID, Okta, Keycloak, any certified OIDC IdP) answers exactly one question: *who is this person?* Everything downstream — which Amendia roles they hold, which tasks they may claim, who is SoD-excluded on a given instance — is answered by Amendia from its own store.

The trust boundary with the IdP is deliberately thin: `iss` + `sub` (plus email/name for display). We never build logic on vendor-shaped claims (Entra group GUIDs and its groups-overage behavior, Okta groups claims, Keycloak `realm_access.roles`) — role/group claims are precisely where IdP portability dies. The litmus test for every auth decision: *would this line change if the customer ran Entra instead of Keycloak?* If yes, it belongs in configuration or behind the mapping layer.

A second principle came free from the existing design: **domain authorization already lives in Amendia.** SoD exclusions, `allowed_decisions`, HITL floors, and side-effect policy never touched identity — they operate on Amendia user ids and roles. This work replaces *who the user is* (the dev sign-in stub) without moving any of that logic.

![Auth components](diagrams/auth-components.svg)

## 2. Component inventory

| # | Component | Where | Responsibility |
|---|---|---|---|
| 1 | Customer IdP | External (dev: Keycloak in compose) | OIDC authentication, token issuance, discovery + JWKS |
| 2 | webui auth module | `webui/src/auth/` | PKCE login, token lifecycle, bearer injection, route protection |
| 3 | `libs/amendia_auth` | Shared library | JWT validation → `Principal`; FastAPI dependencies |
| 4 | Identity service | `backend/services/platform/identity` (:8086) | (iss, sub) → Amendia user mapping, JIT provisioning, role assignments, user/role admin API |
| 5 | Enforcement points | Each service's routers | Role guards on mutating endpoints; existing domain rules (SoD etc.) unchanged |
| 6 | Dev realm & seed | compose + committed realm export | Reproducible Keycloak realm; seed users + native role assignments |

### 2.1 Customer IdP (dev: Keycloak)

Any spec-compliant OIDC provider, integrated exclusively through standards: discovery (`/.well-known/openid-configuration`), Authorization Code + PKCE for the SPA, JWKS for signature verification. Amendia's entire per-deployment IdP configuration is: **issuer URL, SPA client id, expected audience**. Nothing vendor-specific.

Dev: Keycloak container in compose with a committed realm export (`amendia-dev` realm; public client `amendia-webui` with PKCE required and the webui redirect URIs; users riya, marcus, priya with passwords for dev). Deliberately **no roles defined in Keycloak** — role assignments live in Amendia (§2.4), proving the decoupling from day one.

### 2.2 webui auth module

`oidc-client-ts` (+ `react-oidc-context`) — a generic certified OIDC library, not a vendor SDK (MSAL/Okta SDKs are compliant but vendor-tuned; using them re-couples us). Behavior:

- Authorization Code + PKCE; no implicit flow, no ROPC, no client secret (public client).
- Config from two env values (`VITE_OIDC_ISSUER`, `VITE_OIDC_CLIENT_ID`); everything else via discovery.
- Token storage in memory/session per library defaults; silent renew via refresh-token rotation where the IdP supports it, iframe renew otherwise — the library abstracts this.
- A fetch wrapper adds `Authorization: Bearer <access_token>` to every API call; on 401, one silent-renew attempt, then redirect to sign-in.
- Route protection: unauthenticated → sign-in screen; the "Continue with your organization" button becomes the real redirect. **The dev user-switcher retires.** Identity display (name, roles) comes from the identity service's `GET /me` (below), not from token claims — the UI shows *Amendia's* view of the user.

### 2.3 `libs/amendia_auth` (shared library)

Follows the established libs pattern (`amendia_common`, `amendia_contracts`, `amendia_bpmn`). Provides:

- **Validator:** verifies bearer JWTs as a standard OIDC resource server — signature against JWKS (fetched via discovery, cached, key-rotation tolerant), `iss` equals the configured issuer, `aud` contains the configured audience, `exp`/`nbf`. Yields `Principal(iss, sub, email?, name?)`. Rejects with 401 + `WWW-Authenticate`.
- **FastAPI dependencies:** `CurrentPrincipal` (401 if absent/invalid) and `CurrentUser` — Principal resolved to the Amendia user + roles via the identity service (HTTP call with short-TTL in-process cache, ~30–60s, so role changes propagate quickly without per-request lookups).
- **Config:** issuer, audience, JWKS cache TTL; env-prefixed per service. An explicit `AUTH_DISABLED` dev flag (default false) so tests and local hacking don't require a running IdP — never set in compose defaults.

One deliberate consequence of the single-IdP model: no issuer allowlist logic, no issuer→tenant mapping. One issuer per deployment, from config.

### 2.4 Identity service (`platform/identity`, :8086)

The keystone that keeps audit history durable and RBAC IdP-agnostic. Same service layout conventions as the rest of the platform. Owns two aggregates in Mongo:

**`users`** — `{ amendia_user_id (natural key, e.g. "usr-…"), identities: [{iss, sub}], email, display_name, status: active|disabled, created_at/updated_at }`, unique index on `(identities.iss, identities.sub)`. **JIT provisioning:** first authenticated request from an unknown (iss, sub) creates the user (status per config: `IDENTITY_JIT_DEFAULT_STATUS` = active in dev, could be `pending` in hardened deployments). The `identities` array (not a scalar) is what lets a customer migrate IdPs later: re-key the identity, every historical `decided_by`/`actor_log` entry — which stores the *Amendia* user id — stays intact.

**`role_assignments`** — `{ amendia_user_id, role (role.* vocabulary from the contracts), assigned_by, assigned_at }`, unique on (user, role).

**API:** `GET /me` (caller's user + roles — the UI's identity source); `GET /users`, `POST /users/{id}/roles`, `DELETE /users/{id}/roles/{role}`, `POST /users/{id}/disable` (admin endpoints, guarded by a new `role.platform.admin`); internal `POST /resolve-principal` used by `amendia_auth`'s `CurrentUser` (accepts iss/sub, returns user + roles, performs JIT).

**Role strategy is pluggable by design, native by default.** v1 ships strategy (a): assignments stored and administered in Amendia (seeded for the three dev users). Strategy (b) — *claim-mapped*: a per-deployment mapping from whatever claim the customer's IdP emits to Amendia roles, stored in config-forge — is a documented extension point behind the same resolution interface, for enterprises that insist on managing entitlements in their IAM. Either way the resolved output is Amendia's `role.*` vocabulary; contracts never change.

### 2.5 Enforcement points (per service)

All four services mount `amendia_auth`. Baseline: every endpoint requires an authenticated principal except `/health` (and the OpenAPI docs in dev). Role guards on mutations:

| Endpoint(s) | Requirement |
|---|---|
| runtime `POST /hitl-tasks/{id}/claim`, `/decide` | authenticated user; **role from server-side resolution — the role-in-body stub is deleted**; then the existing domain checks (task role match, SoD, allowed_decisions) run on the resolved identity |
| registry mutations (pack submit/validate/activate/deprecate, capability & schema registration) | `role.process.owner` (new role id; assign to priya in seed) |
| identity admin endpoints | `role.platform.admin` |
| stub `POST /exceptions/generate` | any authenticated user (it's a dev source) |
| all reads | any authenticated user |

What explicitly does **not** change: SoD computation, HITL floors, side-effect policy, `allowed_decisions` — already Amendia-native. `decided_by`, `assignee`, `actor_log` now carry real `amendia_user_id`s.

Service-to-service and broker-driven flows (dispatch, replies, engine execution) are **not** OIDC-authenticated in this iteration — they run inside the deployment boundary; mTLS/service tokens are a hardening item, noted out of scope.

## 3. The flows

![Auth flows](diagrams/auth-flows.svg)

**Login (PKCE).** Sign-in screen → redirect to IdP authorize endpoint with PKCE challenge → user authenticates against the customer's IAM (their MFA, their policies — not ours) → code back to the SPA redirect URI → library exchanges code + verifier for tokens → SPA calls `GET /me` → identity service resolves (JIT on first ever login) → UI renders with Amendia identity and roles.

**Every API request.** Bearer JWT → `amendia_auth` validates (sig/iss/aud/exp via cached JWKS) → `CurrentUser` resolves principal → user + roles (cached) → route guard checks the required role → domain logic (SoD, decisions) runs against the Amendia user id.

**Role administration.** Platform admin assigns/revokes `role.*` on users via the **Administration UI** (ADR-014) over the identity API. The *pickable* role list is dynamic — sourced from the registry's `GET /roles`, derived from active packs' bindings, so onboarding a pack makes its roles grantable automatically (ADR-026). Takes effect within the resolution cache TTL.

**IdP migration (the durability story).** Customer replaces Okta with Entra: new issuer configured, users' new (iss, sub) identities linked to their existing Amendia users (admin re-key or matched JIT policy) — zero rewrites of immutable audit records.

## 4. Decisions & rationale (summary)

| Decision | Rationale |
|---|---|
| Generic OIDC lib in SPA, not vendor SDKs | Standards-only integration; two env values swap the IdP |
| Thin trust: iss+sub only; never vendor role/group claims | The single biggest IdP-portability trap, avoided structurally |
| Amendia user id as the identity in all records | Audit immutability survives IdP migration; SoD/decisions unchanged |
| JIT provisioning + identity array | Zero-friction onboarding; re-keyable identities |
| Native role store first, claim-mapping as pluggable strategy | Ship simple; enterprise central-IAM entitlements remain a config feature, not a rearchitecture |
| Roles remain the contracts' `role.*` vocabulary | RBAC *pattern* owned by the platform (`role.*`, shape-validated, no central catalog); the *grantable set* is deployment-specific — derived from active packs' bindings via `GET /roles` (ADR-026) plus two code-fixed platform roles |
| Single-issuer config (deployment = customer) | Tenancy relaxation per deployment model; removes issuer mapping entirely |
| Keycloak realm export committed | Reproducible dev; also the reference integration doc for customer IdPs |

## 5. Out of scope (this iteration)

SCIM provisioning/deprovisioning (the identity model is shaped for it), claim-mapped role strategy implementation (interface reserved), service-to-service auth (mTLS/tokens — deployment-boundary hardening), fine-grained policy engines (OPA/Cedar — current role + domain rules are sufficient), session management UI, audit log of admin role changes beyond `assigned_by/at`, Keycloak theming.

## 6. Implementation order (suggested prompts)

1. **Backend:** `libs/amendia_auth` + identity service + Keycloak in compose (realm export) + enforcement/stub-removal across services + seed role assignments. Everything testable with curl + a Keycloak token before the UI moves.
2. **Frontend:** webui PKCE integration, fetch wrapper, route protection, `/me`-driven identity, retire the user-switcher, update the user guide (§2 sign-in and §6 limitations).
