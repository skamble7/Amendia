// e2e/support/fixtures.ts — the persona-aware test. `test.use({ persona: "marcus" })` picks whose cached auth
// a spec runs under; the `page` fixture restores that persona's sessionStorage token (react-oidc keeps it in
// sessionStorage, which Playwright's storageState does NOT capture) via an init script before the first nav.
// A global preflight (written by global-setup) skips every test cleanly when the stack/webui isn't ready.
import { test as base, expect } from "@playwright/test";
import fs from "node:fs";

import { authSessionFile, authStateFile, preflightFile, type Persona } from "./env";

interface Preflight { ready: boolean; reason?: string; personas?: Record<string, string | true> }

function preflight(): Preflight {
  try {
    return JSON.parse(fs.readFileSync(preflightFile(), "utf8"));
  } catch {
    return { ready: false, reason: "no preflight file — global-setup did not run" };
  }
}

export const test = base.extend<{ persona: Persona }>({
  persona: ["priya", { option: true }],

  // Attach the persona's cookies/localStorage snapshot (KC SSO etc.).
  storageState: async ({ persona }, use) => {
    const f = authStateFile(persona);
    await use(fs.existsSync(f) ? f : undefined);
  },

  page: async ({ page, persona }, use, testInfo) => {
    const pf = preflight();
    if (!pf.ready) testInfo.skip(true, `[stack not ready] ${pf.reason}`);
    if (pf.personas && pf.personas[persona] !== true) {
      testInfo.skip(true, `[login unavailable for ${persona}] ${pf.personas[persona]}`);
    }
    // Restore the OIDC token react-oidc keeps in sessionStorage (storageState can't).
    const sessFile = authSessionFile(persona);
    if (fs.existsSync(sessFile)) {
      const snapshot = JSON.parse(fs.readFileSync(sessFile, "utf8")) as Record<string, string>;
      await page.addInitScript((data) => {
        for (const [k, v] of Object.entries(data)) window.sessionStorage.setItem(k, v as string);
      }, snapshot);
    }
    await use(page);
  },
});

export { expect };
