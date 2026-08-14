// e2e/support/setup.ts — run the deterministic (copilot-free) ACH domain setup/teardown by spawning the
// committed Python driver (fixtures/onboarding/onboard_ach.py). The driver is idempotent (create-only-if-absent)
// and self-contained from an empty, minimally-seeded stack. Env (endpoints/realm) is passed through.
import { spawnSync } from "node:child_process";
import path from "node:path";

import { CFG, E2E_DIR } from "./env";

const DRIVER = path.join(E2E_DIR, "fixtures", "onboarding", "onboard_ach.py");

// A stable-per-run id so fired cases can be tagged/identified for teardown (see fireScenario).
export const RUN_ID = `e2e-${Math.floor(Date.now() / 1000).toString(36)}`;

function runDriver(args: string[]): { ok: boolean; out: string } {
  const env = {
    ...process.env,
    REGISTRY: CFG.registry, IDENTITY: CFG.identity, KEYCLOAK: CFG.keycloak, REALM: CFG.realm,
    CLI_CLIENT: CFG.cliClient, CLI_SECRET: CFG.cliSecret, DEV_PASSWORD: CFG.devPassword,
  };
  const py = process.env.PYTHON || "python3";
  const r = spawnSync(py, [DRIVER, ...args], { env, encoding: "utf8", timeout: 180_000 });
  const out = `${r.stdout || ""}${r.stderr || ""}`.trim();
  return { ok: r.status === 0, out };
}

/** Ensure the ACH domain exists (cohort definition + 3 active packs). Idempotent; safe to call every run. */
export function ensureAchDomain(): { ok: boolean; out: string } {
  return runDriver([]);
}

/** ADR-061 clean-delete the ACH packs + the cohort definition (leave the registry as found). */
export function teardownAchDomain(): { ok: boolean; out: string } {
  return runDriver(["--teardown"]);
}
