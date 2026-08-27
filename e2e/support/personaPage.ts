// e2e/support/personaPage.ts — open a page authenticated as a SPECIFIC persona (a fresh context with that
// persona's cookies + the re-injected sessionStorage token). Used by the HITL arc so each gate is resolved by
// an SoD-correct persona through the UI, even though the whole flow is one test.
import fs from "node:fs";
import { type Browser, type Page } from "@playwright/test";

import { authSessionFile, authStateFile, type Persona } from "./env";

export async function withPersonaPage<T>(
  browser: Browser, persona: Persona, fn: (page: Page) => Promise<T>,
): Promise<T> {
  const stateFile = authStateFile(persona);
  const context = await browser.newContext(fs.existsSync(stateFile) ? { storageState: stateFile } : {});
  const sessFile = authSessionFile(persona);
  if (fs.existsSync(sessFile)) {
    const snapshot = JSON.parse(fs.readFileSync(sessFile, "utf8")) as Record<string, string>;
    await context.addInitScript((data) => {
      for (const [k, v] of Object.entries(data)) window.sessionStorage.setItem(k, v as string);
    }, snapshot);
  }
  const page = await context.newPage();
  try {
    return await fn(page);
  } finally {
    await context.close();
  }
}
