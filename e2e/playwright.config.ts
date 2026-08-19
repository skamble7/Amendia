// playwright.config.ts — the primary FULL-SYSTEM e2e (frontend + backend + stubs + DB), a top-level suite (not a
// webui concern). Serves the webui via `vite dev` (its proxy points `/api/*` at the running compose backend), logs
// each persona in once (global-setup), and runs the broad journeys under ./tests. Degrades: global-setup writes a
// skip flag if the backend/webui isn't reachable.
import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BASE_URL = process.env.E2E_BASE_URL?.trim() || "http://localhost:5173";
// The webui lives one level up — the only cross-boundary tie (its build/serve). Nothing here imports webui src.
const WEBUI_DIR = path.resolve(__dirname, "../webui");

export default defineConfig({
  testDir: "./tests",
  // The copilot/LLM lifecycle spec is NON-BLOCKING and runs only via its own command (tools/e2e-copilot.sh →
  // playwright.copilot.config.ts). Exclude it from the deterministic gate so `bash tools/e2e.sh` never depends on
  // the LLM.
  testIgnore: ["**/ach-copilot-lifecycle.spec.ts"],
  outputDir: "./.artifacts",
  globalSetup: "./global-setup.ts",
  globalTeardown: "./global-teardown.ts",
  fullyParallel: false,          // shared backend state (one onboarded stack) — keep runs deterministic
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 120_000,              // browser journeys incl. the HITL arc can take a couple of minutes
  expect: { timeout: 15_000 },
  reporter: [["list"], ["html", { outputFolder: ".report", open: "never" }]],
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 20_000,
    navigationTimeout: 30_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // Reuse an already-running dev server (tools/e2e.sh / `npm run dev`), else start one — from the webui dir (vite
  // is CWD-sensitive). The vite proxy sends /api/* to the compose backend via VITE_*_URL (the 18xxx defaults in
  // webui/.env).
  webServer: {
    command: "npm run dev -- --port 5173 --strictPort",
    cwd: WEBUI_DIR,
    url: BASE_URL,
    reuseExistingServer: true,
    timeout: 120_000,
    stdout: "ignore",
    stderr: "pipe",
  },
});
