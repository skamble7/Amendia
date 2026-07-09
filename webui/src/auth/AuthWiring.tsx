import { useEffect } from "react";
import { useAuth } from "react-oidc-context";
import { configureAuthBridge } from "./authToken";

/**
 * Connects the OIDC context to the module-level auth bridge the API client uses.
 * Renders nothing. Kept re-run on every auth change so the token getter always
 * reflects the freshest access token.
 */
export function AuthWiring() {
  const auth = useAuth();

  useEffect(() => {
    configureAuthBridge({
      getToken: () => auth.user?.access_token,
      renew: async () => {
        try {
          const user = await auth.signinSilent();
          return user?.access_token ?? undefined;
        } catch {
          return undefined;
        }
      },
      // Full sign-in, preserving where the user was so they land back there.
      onAuthLost: () => {
        void auth.signinRedirect({ state: window.location.pathname + window.location.search });
      },
    });
  }, [auth]);

  return null;
}
