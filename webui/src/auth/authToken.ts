/**
 * Auth bridge: a tiny module-level seam so the plain `request()` fetch wrapper
 * (not a React hook) can reach the current access token, trigger a silent renew,
 * and hand off to a full sign-in when auth is lost. `AuthWiring` (inside the OIDC
 * provider) wires the real implementations; tests configure a fake token here.
 */
type Getter = () => string | undefined;
type Renew = () => Promise<string | undefined>;
type Lost = () => void;

let _get: Getter = () => undefined;
let _renew: Renew = async () => undefined;
let _lost: Lost = () => {};

export function configureAuthBridge(opts: { getToken: Getter; renew: Renew; onAuthLost: Lost }): void {
  _get = opts.getToken;
  _renew = opts.renew;
  _lost = opts.onAuthLost;
}

/** Test helper: pin a static token (and no-op renew/lost) for the network layer. */
export function setTestToken(token: string | undefined): void {
  _get = () => token;
  _renew = async () => token;
  _lost = () => {};
}

export const authBridge = {
  token: (): string | undefined => _get(),
  renew: (): Promise<string | undefined> => _renew(),
  onAuthLost: (): void => _lost(),
};
