# ADR-053 — Headless / API-first operation (service principals and HITL-over-API)

**Status:** Proposed (2026-07-29)
**Related:** `amendia_auth_architecture.md` (authenticate-with-IAM / authorize-in-Amendia, identity service, JIT, native role store), ADR-047 (platform domain neutrality), ADR-048–052 (the executable model + the onboarding surfaces that write to it), `webui_user_guide.md` (nav is progressive disclosure, not enforcement), and the recent nav domain-neutrality fix (`webui/src/lib/roles.ts` `isOperator` — operator surfaces gate on holding any role other than `role.platform.admin`, no pack role ids enumerated).

## Context

A question surfaced while fixing the nav-gating bug: *are roles enforced on the frontend, and could Amendia run headless later?* The answer to the first is **no** — and that answer is precisely what makes the second cheap.

The web UI is a **thin client**. Nav visibility is progressive disclosure only; the guide is explicit that "reads stay role-free server-side... those pages are still reachable by direct URL." Real enforcement lives entirely in the backend and is **client-agnostic**: `amendia_auth` validates a bearer JWT as a standard OIDC resource server; `CurrentUser` resolves `(iss, sub)` to a durable Amendia `usr-…` id + roles; route guards check the required `role.*` on mutations; and the domain rules that actually matter — separation of duties, `allowed_decisions`, HITL floors, and the side-effect→`approve_actions` coupling — were never coupled to identity or to any client. They operate on Amendia user ids and roles, computed per process instance from who actually acted.

The consequence is that **Amendia is already substantially headless-capable by construction.** Every operator action is an HTTP API; capability and artifact-schema registration are already API-only; the onboarding commit chain is *the same ordered, idempotent chain the seeder uses*; reads are open to any authenticated principal. Nothing about removing or bypassing the UI weakens security, because the UI was never a security boundary.

What is missing is not architecture — it is **first-class support**: a non-interactive way for a machine to authenticate, a documented contract for satisfying human-in-the-loop gates over the API, and a guarantee that no operator action is UI-only. This ADR names headless operation as a supported mode and scopes the small, deliberate work to make it real.

## Decision

**Adopt headless / API-first operation as a first-class mode, resting on three pillars — none of which changes the enforcement model, which stays server-side and client-agnostic.**

1. **Service-principal identity via OIDC client-credentials — no new auth architecture.**
   A confidential IdP client obtains a token via the client-credentials grant (Keycloak in dev; any certified OIDC IdP in production). `amendia_auth` validates it exactly like a human bearer token — signature via cached JWKS, `iss`/`aud`/`exp`/`nbf` — and yields a `Principal`. That principal resolves through the identity service's existing `(iss, sub)` → Amendia-user mapping with JIT provisioning, producing a durable `usr-…` for the service account. A platform admin grants it roles from the same `role.*` vocabulary in the same store. A service principal is simply a `Principal` that is not a person; the identity record carries a `kind: service` attribute for auditability, but **authorization stays purely role-based** — no code path branches on principal kind to grant access.

2. **HITL-over-API as a documented, first-class contract.**
   The existing `GET/POST /hitl-tasks/{id}` list / claim / decide endpoints *are* the headless decisioning surface. A headless decider is an authenticated principal holding the required role; SoD exclusions, `allowed_decisions`, and the side-effect→`approve_actions` floor all still apply, unchanged, computed against its Amendia id and recorded honestly in the `actor_log` / `decided_by`. **Explicit governance stance:** whether a *machine* principal may hold a decision role — especially an approver / authorize-actions role — is a **per-deployment policy decision, not a platform relaxation.** The platform enforces identical floors regardless of principal kind; it does not silently let automation bypass four-eyes intent. The recommended default is that side-effectful authorization gates are **human-only by policy** (configurable per deployment), so going headless never *technically* lowers a control and never *accidentally* removes a human from the money-moving signature.

3. **API-completeness guarantee.**
   Every operator / process-owner / platform-admin action must have a documented, role-guarded API equivalent with **no UI-only path**. Headless onboarding is driving the onboarding-session endpoints (or submitting a pre-composed manifest through the same commit chain the seeder runs); headless exception intake is the ingestor's real event path (`/resolve` + domain events), not the dev stub button. This pillar is an audit plus a published *headless client contract* covering auth, onboarding, exception intake, task decisioning, and reads.

Because all three write to and read from the neutral model (ADR-047) through the existing enforcement points, headless operation keeps the platform **domain-agnostic**: no domain logic, and no client assumption, enters the platform.

## Consequences

- **+** Integrations, CI/CD pack promotion, automated deciders, alternative UIs, and other systems become first-class consumers with **identical enforcement** — the UI becomes provably optional rather than incidentally so.
- **+** Reaffirms and leans on the server-side, domain-neutral enforcement model. Headless is the proof that authorization was correctly placed.
- **+** The identity model was already shaped for this: the `identities` array, native role store, JIT provisioning, and the pluggable claim-mapping extension point all apply to service principals without change.
- **−** Service principals holding decision roles is a **governance surface** that must be deliberately controlled. The platform can never be *technically* bypassed (SoD and the side-effect floor hold for any principal), but a deployment that grants a machine an approver role has made a policy choice about four-eyes. Mitigated by pillar 2's default-human stance for side-effectful gates, made explicit and configurable.
- **−** Client-credentials tokens carry no human MFA; **secret / token lifecycle** (rotation, least-privilege scoping, revocation) becomes a security responsibility the human PKCE flow didn't have. This is a deployment concern, called out here so it is owned rather than discovered.
- **−** This is distinct from **service-to-service / broker auth** (dispatch, replies, engine execution), which run inside the deployment boundary and remain unauthenticated in this iteration (mTLS/service tokens are a separate hardening item). Headless external callers come through the front-door APIs with a bearer token and use the ordinary OIDC resource-server path — they are *not* the internal S2S case.

## Rollout (phased)

- **Phase 0 — document what is already true (now).** Server-side enforcement, the full operator-action API surface, API-only capability/schema registration, and the seeder-as-headless-onboarding chain already exist. Publish a short "headless-capable surface today" note so the capability is discoverable before any new code lands.
- **Phase 1 — service-principal auth.** Add a confidential client + client-credentials validation path in `amendia_auth` (likely already validates unchanged; confirm and test), a `kind: service` marking on identity records, and admin provisioning / role-grant for service accounts. Testable with a client-credentials token via curl before anything else.
- **Phase 2 — HITL-over-API contract + governance.** Document the decisioning contract; add the per-deployment policy switch for machine principals on side-effectful gates (default human-only); ensure `actor_log` honesty for service deciders.
- **Phase 3 — completeness audit + reference client.** Assert (in test) that no operator action is UI-only; publish the headless client guide; ship a reference headless client (CLI or script) that exercises onboard → raise → decide → read end-to-end in CI, so the mode stays working, not aspirational.

## Non-goals

- **Not** removing or de-prioritizing the web UI — headless is an *additional* surface, and the business-facing onboarding (ADR-052) remains the front door for people.
- **Not** service-to-service / broker authentication (mTLS/service tokens) — that is the internal deployment-boundary hardening item, tracked separately.
- **Not** relaxing any HITL floor, SoD constraint, or side-effect policy — headless callers are subject to identical enforcement.
- **Not** SCIM / automated principal lifecycle — the identity model is shaped for it, but joiner/mover/leaver automation is a separate track.
- **Not** implementing the claim-mapped role strategy — it remains the reserved extension point from the auth architecture; service principals use the native role store like everyone else.
