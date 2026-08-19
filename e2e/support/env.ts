// e2e/support/env.ts — endpoints + personas for the Playwright e2e (compose host-port defaults, env-overridable).
// Mirrors backend/tests/smoke/config.py so the two e2e layers point at the same stack.
import path from "node:path";
import { fileURLToPath } from "node:url";

const _dir = path.dirname(fileURLToPath(import.meta.url));
export const E2E_DIR = path.resolve(_dir, "..");
export const AUTH_DIR = path.join(E2E_DIR, ".auth");
export const SCENARIOS_DIR = path.resolve(E2E_DIR, "../backend/tests/smoke/scenarios");

const env = (k: string, d: string) => (process.env[k]?.trim() ? process.env[k]!.trim() : d);

export const CFG = {
  // The served webui (Playwright baseURL). vite dev on 5173 (its registered OIDC redirect origin).
  webui: env("E2E_BASE_URL", "http://localhost:5173"),
  // Backend compose host ports (the vite proxy targets; also used directly by fireScenario/preflight).
  ingestor: env("INGESTOR", "http://localhost:18082"),
  runtime: env("RUNTIME", "http://localhost:18083"),
  registry: env("REGISTRY", "http://localhost:18084"),
  glea: env("GLEA", "http://localhost:18090"),
  stub: env("STUB", "http://localhost:18081"),
  pegaStub: env("PEGA_STUB", "http://localhost:9095"),
  identity: env("IDENTITY", "http://localhost:18086"),
  notification: env("NOTIFICATION", "http://localhost:18088"),
  keycloak: env("KEYCLOAK", "http://localhost:8087"),
  realm: env("REALM", "amendia-dev"),
  // For fireScenario's stub_generator bearer (mirrors the demo's dev CLI client).
  cliClient: env("CLI_CLIENT", "amendia-dev-cli"),
  cliSecret: env("CLI_SECRET", "dev-cli-secret"),
  devPassword: env("DEV_PASSWORD", "dev-password"),
};

export type Persona = "priya" | "marcus" | "riya";
export const PERSONAS: Persona[] = ["priya", "marcus", "riya"];

export const tokenUrl = () =>
  `${CFG.keycloak}/realms/${CFG.realm}/protocol/openid-connect/token`;
export const oidcConfigUrl = () =>
  `${CFG.keycloak}/realms/${CFG.realm}/.well-known/openid-configuration`;

export const authStateFile = (p: Persona) => path.join(AUTH_DIR, `${p}.state.json`);
export const authSessionFile = (p: Persona) => path.join(AUTH_DIR, `${p}.session.json`);
export const preflightFile = () => path.join(AUTH_DIR, "preflight.json");

// Core services that must answer for the suite to run (a driver-specific one is checked per scenario).
export const coreHealth = (): Record<string, string> => ({
  "agent-runtime": `${CFG.runtime}/health`,
  "process-registry": `${CFG.registry}/health`,
  "glea-service": `${CFG.glea}/health`,
  ingestor: `${CFG.ingestor}/health`,
  keycloak: oidcConfigUrl(),
});
