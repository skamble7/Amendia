import { WebStorageStateStore } from "oidc-client-ts";
import type { AuthProviderProps } from "react-oidc-context";

/**
 * OIDC (Authorization Code + PKCE) configuration — from env only. Everything
 * else (endpoints, JWKS) is discovered from the issuer. Two values swap the IdP:
 * in production these point at the customer's own IAM (Entra / Okta / …). The
 * browser talks to the issuer directly (redirect + silent renew); it is never
 * proxied through the app origin.
 */
const issuer = import.meta.env.VITE_OIDC_ISSUER ?? "http://localhost:8087/realms/amendia-dev";
const clientId = import.meta.env.VITE_OIDC_CLIENT_ID ?? "amendia-webui";

const origin = typeof window !== "undefined" ? window.location.origin : "http://localhost:5173";

export const CALLBACK_PATH = "/auth/callback";
export const SIGNIN_PATH = "/signin";

export const oidcConfig: AuthProviderProps = {
  authority: issuer,
  client_id: clientId,
  redirect_uri: `${origin}${CALLBACK_PATH}`,
  post_logout_redirect_uri: `${origin}${SIGNIN_PATH}`,
  response_type: "code",
  scope: "openid profile email",
  // Refresh-token rotation is enabled on the client, so the library renews via
  // the refresh_token grant in the background — no login interruption.
  automaticSilentRenew: true,
  // Tokens live in sessionStorage (cleared when the tab closes), per library defaults.
  userStore: new WebStorageStateStore({ store: window.sessionStorage }),
  // After the library exchanges the code, drop ?code&state from the URL so a
  // refresh/back doesn't replay it. The callback route then restores the deep link.
  onSigninCallback: () => {
    window.history.replaceState({}, document.title, CALLBACK_PATH);
  },
};
