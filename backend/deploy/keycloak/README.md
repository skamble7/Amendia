# Keycloak dev IdP (`amendia-dev` realm)

Keycloak stands in for the customer's identity provider in local dev. It runs in
compose on **:8087** in `start-dev` mode and imports the committed realm export
(`amendia-dev-realm.json`) on startup. This file doubles as the reference for
integrating a real customer IdP (see **Customer integration** below).

## What the realm contains

- **Realm `amendia-dev`** — dev token lifetimes: access token ~5m
  (`accessTokenLifespan: 300`), refresh ~30m idle (`ssoSessionIdleTimeout: 1800`),
  refresh-token rotation on (`revokeRefreshToken: true`, `refreshTokenMaxReuse: 0`).
- **Public client `amendia-webui`** — the SPA. Authorization Code + **PKCE (S256)
  required**, no client secret, redirect URIs + web origins for Vite dev
  (`http://localhost:5173/*`) and the composed webui (`http://localhost:8085/*`).
  Direct-access (password) grants are **disabled** here — never enable them on the
  browser client.
- **Confidential client `amendia-dev-cli`** — dev-only, **direct-access grants
  enabled** so `curl` can mint tokens via the password grant (secret
  `dev-cli-secret`). This exists so ROPC is confined to a throwaway client and is
  never turned on for `amendia-webui`. Do not ship this client to a customer.
- **Audience `amendia-api`** — added by a per-client audience mapper on both clients
  (see below).
- **Users** `riya`, `marcus`, `priya`, `alex`, `sam` — password `dev-password`
  (non-temporary), emails `<user>@amendia.dev`, names set. `alex` is seeded (by
  email) with **`role.platform.admin` only** — he exercises the admin-only nav
  composition (Administration and nothing else). `sam` has **no** staged roles, so
  his first sign-in lands in the roleless "no access yet" state.
  **Amendia users are born only by JIT** — the identity seed writes *pending* role
  assignments keyed by email and nothing is created in Mongo until each user first
  signs in through Keycloak. Do not hand-insert provisioned users.
- **Deliberately zero realm/client roles for our personas.** Role assignments live
  in Amendia (the identity service seed), proving the decoupling: authenticate with
  the IdP, authorize in Amendia. We never read `realm_access` / `groups` claims.

## Audience — how services verify `aud`

Amendia resource servers require `aud` to contain a stable `amendia-api` value. Each
client (`amendia-webui`, `amendia-dev-cli`) carries a built-in **Audience protocol
mapper** (`oidc-audience-mapper`, `included.custom.audience: amendia-api`,
`access.token.claim: true`) in its `protocolMappers`, so every issued access token
carries `"aud": [..., "amendia-api"]`.

Why a per-client mapper rather than a custom client *scope*: in a hand-written realm
export, declaring a `clientScopes` array **replaces** Keycloak's built-in scopes,
which in Keycloak 26 drops the `basic` scope — and with it the `sub` claim, breaking
every token. A per-client mapper leaves the built-in default scopes intact
(`sub`/`email`/`profile` all present) and still adds the audience. Both mechanisms
are spec-equivalent; for a customer's IAM the ask is the same: emit `amendia-api` in
`aud` (via an audience/resource indicator, however their IdP models it).

## Admin console

`http://localhost:8087/` → admin / admin (`KC_BOOTSTRAP_ADMIN_USERNAME/PASSWORD` in
compose). Select the **amendia-dev** realm (top-left dropdown) to inspect the seeded
users (riya / marcus / priya / alex / sam).

**"We are sorry… HTTPS required" on the admin console?** That's the built-in `master`
realm (which backs the admin console), not `amendia-dev`. Its default `sslRequired`
is `external`, and requests arriving through Docker's port mapping trip it over plain
HTTP. `amendia-dev` sets `sslRequired: none` (why the app's own sign-in works over
HTTP), but the committed export can't touch `master`. One-time fix per fresh stack
(kcadm runs *inside* the container, where it's genuinely localhost and unaffected):

```bash
docker exec deploy-keycloak-1 /opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8080 --realm master --user admin --password admin
docker exec deploy-keycloak-1 /opt/keycloak/bin/kcadm.sh update realms/master -s sslRequired=NONE
```

Dev-mode Keycloak uses ephemeral H2, so re-run this after a `docker compose down` +
recreate. It affects only the admin console — the Amendia app never touches `master`.

## Minting a token with curl (dev only)

Password grant is acceptable **for dev curl-testing only**, and only via the
dev-only `amendia-dev-cli` client (never `amendia-webui`):

```bash
curl -s http://localhost:8087/realms/amendia-dev/protocol/openid-connect/token \
  -d grant_type=password \
  -d client_id=amendia-dev-cli \
  -d client_secret=dev-cli-secret \
  -d username=riya -d password=dev-password \
  -d scope=openid | jq -r .access_token
```

Caveat: ROPC (password grant) is a dev convenience that bypasses the browser +
PKCE flow. Real logins go through Authorization Code + PKCE on `amendia-webui`.

## The dev-networking footgun (read this)

Tokens are minted with the **browser-facing issuer**
`http://localhost:8087/realms/amendia-dev` (set via `KC_HOSTNAME=http://localhost:8087`)
so the SPA redirect and the services' `iss` check agree. But `localhost:8087` is
**not reachable from inside the compose network**. So each service:

- validates `iss` against `http://localhost:8087/realms/amendia-dev` (its
  `*_AUTH_ISSUER`), and
- fetches JWKS from the **internal alias**
  `http://keycloak:8080/realms/amendia-dev/protocol/openid-connect/certs` (its
  `*_AUTH_JWKS_URI`), which bypasses OIDC discovery (discovery would hand back a
  `jwks_uri` pointing at the unreachable `localhost:8087`).

If you ever see `jwks_unavailable` or `wrong_issuer` errors, this is the first
thing to check.

## Customer IdP integration (the three things their IAM team provides)

Amendia's entire per-deployment IdP configuration is three values — nothing
vendor-specific:

1. **Issuer URL** — e.g. `https://login.customer.com/oidc`. Amendia validates `iss`
   and discovers JWKS from it (`*_AUTH_ISSUER`; drop `*_AUTH_JWKS_URI` in a real
   deployment where the issuer host is reachable).
2. **Public SPA client** — Authorization Code + **PKCE (S256)**, the Amendia webui
   redirect URIs registered, no client secret.
3. **Audience** — issue Amendia access tokens with `aud` containing `amendia-api`
   (`*_AUTH_AUDIENCE`), via whatever audience/resource-indicator mechanism their IdP
   offers (the per-client audience mapper here is the Keycloak example).

Roles are **not** taken from the IdP — they are administered in Amendia's identity
service. That is what makes the integration portable across Entra / Okta / Keycloak.
