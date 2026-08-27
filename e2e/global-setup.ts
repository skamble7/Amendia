// e2e/global-setup.ts — run once. Preflight the backend, then automate the OIDC auth-code login through the
// Keycloak page ONCE per persona and snapshot each persona's auth (cookies via storageState + the token that
// react-oidc keeps in sessionStorage). Degrades: if the backend/webui isn't reachable, write a skip flag and
// return (tests skip cleanly) rather than crashing the run.
import { chromium, type FullConfig } from "@playwright/test";
import fs from "node:fs";

import { AUTH_DIR, CFG, PERSONAS, authSessionFile, authStateFile, preflightFile, type Persona } from "./support/env";
import { stackDownReason } from "./support/backend";
import { ensureAchDomain } from "./support/setup";

async function webuiReachable(timeoutMs = 90_000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(CFG.webui, { signal: AbortSignal.timeout(3000) });
      if (r.ok || r.status < 500) return true;
    } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 1500));
  }
  return false;
}

async function loginPersona(persona: Persona): Promise<void> {
  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();
  try {
    await page.goto(`${CFG.webui}/signin`, { waitUntil: "domcontentloaded" });
    const cta = page.getByRole("button", { name: /Continue with your organization/i });
    if (await cta.isVisible().catch(() => false)) await cta.click();

    // Keycloak login form (standard theme ids).
    await page.waitForURL(/\/realms\/[^/]+\/(protocol\/openid-connect\/auth|login-actions)/, { timeout: 30_000 });
    await page.locator("#username").fill(persona);
    await page.locator("#password").fill(CFG.devPassword);
    await page.locator("#kc-login, input[type=submit], button[type=submit]").first().click();

    // Back on the app, authenticated — the nav (Cohorts) only renders past RequireAuth.
    await page.waitForURL((u) => new URL(u).origin === new URL(CFG.webui).origin && !new URL(u).pathname.startsWith("/signin"),
      { timeout: 30_000 });
    await page.getByRole("link", { name: "Cohorts" }).first().waitFor({ timeout: 30_000 });

    const session = await page.evaluate(() => JSON.stringify(sessionStorage));
    fs.writeFileSync(authSessionFile(persona), session);
    await context.storageState({ path: authStateFile(persona) });
  } finally {
    await browser.close();
  }
}

export default async function globalSetup(_config: FullConfig) {
  fs.mkdirSync(AUTH_DIR, { recursive: true });

  const down = await stackDownReason();
  if (down) {
    fs.writeFileSync(preflightFile(), JSON.stringify({ ready: false, reason: down }));
    console.warn(`\n[e2e] SKIPPING: ${down}\n`);
    return;
  }

  // Self-contained: deterministically ensure the ACH domain (cohort definition + 3 active packs) from an empty,
  // minimally-seeded registry — copilot-free, idempotent. If it can't complete, the ACH execution journeys skip
  // (they re-check onboarded packs), never hard-fail.
  const setup = ensureAchDomain();
  console.log(`\n[e2e] ACH domain setup:\n${setup.out}\n`);
  if (!setup.ok) console.warn("[e2e] ACH setup incomplete — ACH execution journeys will skip.");
  if (!(await webuiReachable())) {
    const reason = `webui not served at ${CFG.webui} — start it (tools/e2e.sh does this) or set E2E_BASE_URL`;
    fs.writeFileSync(preflightFile(), JSON.stringify({ ready: false, reason }));
    console.warn(`\n[e2e] SKIPPING: ${reason}\n`);
    return;
  }

  const personas: Record<string, string | true> = {};
  for (const p of PERSONAS) {
    try {
      await loginPersona(p);
      personas[p] = true;
    } catch (e) {
      personas[p] = String(e);
      console.warn(`[e2e] login failed for ${p}: ${e}`);
    }
  }
  fs.writeFileSync(preflightFile(), JSON.stringify({ ready: true, personas }));
}
