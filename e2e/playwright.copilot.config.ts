// playwright.copilot.config.ts — the NON-BLOCKING copilot/LLM lifecycle command (tools/e2e-copilot.sh). Runs ONLY
// `ach-copilot-lifecycle.spec.ts`, which onboards the 3 ACH segments via the REAL copilot autopilot, forms the
// cohort, drives the 3 pega flows, and RETAINS everything (no globalTeardown). Skips cleanly when the stack has no
// copilot model (502 copilot_llm_unavailable). Separate from playwright.config.ts so the deterministic gate never
// runs the LLM and this run never runs the deterministic ACH onboarding.
import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BASE_URL = process.env.E2E_BASE_URL?.trim() || "http://localhost:5173";
const WEBUI_DIR = path.resolve(__dirname, "../webui");

export default defineConfig({
  testDir: "./tests",
  testMatch: ["**/ach-copilot-lifecycle.spec.ts"],   // ONLY the copilot lifecycle spec
  outputDir: "./.artifacts-copilot",
  globalSetup: "./global-setup.copilot.ts",           // logins + preflight ONLY — no deterministic ACH onboarding
  // NO globalTeardown — retain the onboarded packs / cohort / instances / roles for inspection.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,                                          // real LLM run — no auto-retry (would re-onboard duplicate packs)
  timeout: 600_000,                                    // live model onboarding (3 segments) + 3 pega flows
  expect: { timeout: 20_000 },
  reporter: [["list"], ["html", { outputFolder: ".report-copilot", open: "never" }]],
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 30_000,
    navigationTimeout: 30_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
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
