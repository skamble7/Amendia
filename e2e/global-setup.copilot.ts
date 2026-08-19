// e2e/global-setup.copilot.ts — global setup for the COPILOT lifecycle command only. Same persona-login +
// preflight snapshot as the deterministic global-setup, but it does NOT run the deterministic ACH onboarding
// (ensureAchDomain) — the copilot spec does its OWN onboarding via the real LLM autopilot in-browser, on a clean
// stack. It also does not tear anything down (playwright.copilot.config.ts declares no globalTeardown).
//
// Login timing note: personas are logged in here (before the spec onboards + grants the copilot roles). The
// snapshotted bearer is still valid — the ACH `role.*` roles are resolved SERVER-side per request (amendia_auth,
// (iss,sub) 30s cache), so a token minted now picks up roles granted later once the cache turns over. The spec
// polls for role materialisation before driving gates (mirrors the deterministic structural check).
import { chromium, type FullConfig } from "@playwright/test";
import fs from "node:fs";

import { AUTH_DIR, CFG, PERSONAS, authSessionFile, authStateFile, preflightFile, type Persona } from "./support/env";
import { stackDownReason } from "./support/backend";

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

async function loginOnce(persona: Persona): Promise<void> {
  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();
  try {
    await page.goto(`${CFG.webui}/signin`, { waitUntil: "domcontentloaded" });
    const cta = page.getByRole("button", { name: /Continue with your organization/i });
    if (await cta.isVisible().catch(() => false)) await cta.click();

    await page.waitForURL(/\/realms\/[^/]+\/(protocol\/openid-connect\/auth|login-actions)/, { timeout: 30_000 });
    await page.locator("#username").fill(persona);
    await page.locator("#password").fill(CFG.devPassword);
    await page.locator("#kc-login, input[type=submit], button[type=submit]").first().click();

    await page.waitForURL((u) => new URL(u).origin === new URL(CFG.webui).origin && !new URL(u).pathname.startsWith("/signin"),
      { timeout: 30_000 });
    await page.getByRole("link", { name: "Cohorts" }).first().waitFor({ timeout: 45_000 });

    const session = await page.evaluate(() => JSON.stringify(sessionStorage));
    fs.writeFileSync(authSessionFile(persona), session);
    await context.storageState({ path: authStateFile(persona) });
  } finally {
    await browser.close();
  }
}

// Retry once — a single persona's post-login nav hydration can occasionally miss the 45s window under load; a fresh
// context reliably clears it. (The flows drive gates via this snapshot, so a stale/failed one must not slip through.)
async function loginPersona(persona: Persona): Promise<void> {
  try {
    await loginOnce(persona);
  } catch (e) {
    console.warn(`[e2e:copilot] login retry for ${persona} (first attempt: ${e})`);
    await loginOnce(persona);
  }
}

export default async function globalSetup(_config: FullConfig) {
  fs.mkdirSync(AUTH_DIR, { recursive: true });

  const down = await stackDownReason();
  if (down) {
    fs.writeFileSync(preflightFile(), JSON.stringify({ ready: false, reason: down }));
    console.warn(`\n[e2e:copilot] SKIPPING: ${down}\n`);
    return;
  }
  if (!(await webuiReachable())) {
    const reason = `webui not served at ${CFG.webui} — start it (tools/e2e-copilot.sh does this) or set E2E_BASE_URL`;
    fs.writeFileSync(preflightFile(), JSON.stringify({ ready: false, reason }));
    console.warn(`\n[e2e:copilot] SKIPPING: ${reason}\n`);
    return;
  }

  const personas: Record<string, string | true> = {};
  for (const p of PERSONAS) {
    try {
      await loginPersona(p);
      personas[p] = true;
    } catch (e) {
      personas[p] = String(e);
      console.warn(`[e2e:copilot] login failed for ${p}: ${e}`);
    }
  }
  fs.writeFileSync(preflightFile(), JSON.stringify({ ready: true, personas }));
}
