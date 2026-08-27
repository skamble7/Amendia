// e2e/pages/screens.ts — light page objects: stable role/text selectors over the real screens. A minimal set of
// data-testid hooks was added to the webui only where a stable anchor was genuinely missing (see README).
import { type Page, type Locator, expect } from "@playwright/test";

export class Nav {
  constructor(private page: Page) {}
  async go(label: "Dashboard" | "Task inbox" | "Instances" | "Cohorts" | "Triggers" | "Registry") {
    await this.page.getByRole("link", { name: label }).first().click();
  }
}

export class Cohorts {
  constructor(private page: Page) {}
  async open() { await this.page.goto("/cohorts"); }
  tab(name: "instances" | "definitions"): Locator {
    return this.page.getByRole("tab", { name: new RegExp(name, "i") });
  }
  async openDefinitions() { await this.tab("definitions").click(); }
  row(text: string): Locator { return this.page.getByRole("row", { name: new RegExp(text) }); }
  async openInstanceByCorrelation(value: string) {
    await this.page.goto(`/cohorts/by-correlation/${value}`);
  }
}

export class CohortDefinition {
  constructor(private page: Page) {}
  async open(defId: string) { await this.page.goto(`/cohorts/definitions/${defId}`); }
  editBtn(): Locator { return this.page.getByRole("button", { name: /Edit definition/i }); }
  saveBtn(): Locator { return this.page.getByRole("button", { name: /^Save$/i }); }
  graphCard(): Locator { return this.page.getByText("Expectation graph & SLAs"); }
  async startEdit() { await this.editBtn().click(); }
  async addNode(id: string) {
    await this.page.getByLabel(/new node id/i).fill(id);
    await this.page.getByLabel(/new node id/i).press("Enter");
  }
  async addEdge() { await this.page.getByRole("button", { name: /Add edge/i }).click(); }
  async addEndToEndSla() {
    await this.page.getByText("End-to-end SLA").locator("..").getByRole("button", { name: /^Add$/ }).click();
  }
}

export class OnboardingWizard {
  constructor(private page: Page) {}
  async newSession(packKey: string, opts?: { version?: string; title?: string }) {
    await this.page.goto("/registry/onboard/technical");
    await this.page.getByPlaceholder("wire-repair-standard").fill(packKey);
    if (opts?.version) await this.page.getByPlaceholder("1.0.0").fill(opts.version);
    if (opts?.title) await this.page.getByPlaceholder(/Wire repair/i).fill(opts.title);
    // The StartScreen's "Create & continue" opens the copilot route; grab the new session id and jump to the
    // TECHNICAL wizard (the one with the BPMN upload + condition-normalization banner).
    await this.page.getByRole("button", { name: /Create & continue/i }).click();
    await this.page.waitForURL(/\/registry\/onboard\/(?!technical)[^/]+$/, { timeout: 20_000 });
    const sessionId = new URL(this.page.url()).pathname.split("/").pop();
    await this.page.goto(`/registry/onboard/technical/${sessionId}`);
    const toBpmn = this.page.getByRole("button", { name: /Continue to BPMN/i });
    await toBpmn.click(); // fresh session opens on Basics; advance to the BPMN step
    await this.page.getByText(/BPMN process definition/i).waitFor({ timeout: 20_000 });
  }
  async uploadBpmn(absPath: string) {
    await this.page.locator('input[type="file"]').setInputFiles(absPath);
  }
  normalizationNotice(): Locator {
    return this.page.getByText(/Converted \d+ gateway condition/i);
  }
}

export class TaskInbox {
  constructor(private page: Page) {}
  async open() { await this.page.goto("/inbox"); }
  /** The open/claimed task rows for a given instance are links to /inbox/<taskId>. */
  taskRows(): Locator { return this.page.getByRole("row"); }
}

/** Drive ONE HITL task through the Task-Inbox detail UI: claim, author its artifact(s) via the raw-JSON editor
 * (when `edits` is given, e.g. a manual gate's output), and submit. Everything here is real user interaction. */
export async function resolveTaskOnPage(
  page: Page, edits?: Record<string, unknown> | null,
): Promise<void> {
  // The primary submit label varies by gate variant: manual → "Complete task"/"Approve"; approve_result/review
  // → "Approve"; approve_actions → "Authorize all"/"Authorize N".
  const submitName = /^Complete task$|^Approve$|^Authorize (all|\d+)$/;
  // Wait for the task detail to actually RENDER (a claim gate or the decision buttons) before deciding whether a
  // claim is needed — checking too early (page still loading) would wrongly conclude "no claim button".
  await page.getByRole("button", { name: new RegExp(`^Claim task$|${submitName.source}`) }).first()
    .waitFor({ state: "visible", timeout: 20_000 });
  // Claim (open → claimed by me); the claim mutation invalidates the task query, so the fieldset then enables.
  const claim = page.getByRole("button", { name: /^Claim task$/i });
  if (await claim.isVisible().catch(() => false)) {
    await claim.click();
    await expect(claim).toHaveCount(0, { timeout: 15_000 }); // claimed → claim gate hides
  }
  await expect(page.getByRole("button", { name: submitName }).first()).toBeEnabled({ timeout: 20_000 });

  // Author the artifact(s) via the raw-JSON editor (manual gates that produce an output). The tab LABEL is
  // humanized ("release_authorization" → "Release authorization"), so match on either separator/case.
  if (edits) {
    for (const [artifactName, value] of Object.entries(edits)) {
      const tab = page.getByRole("tab", { name: new RegExp(artifactName.replace(/_/g, "[ _]"), "i") });
      if (await tab.isVisible().catch(() => false)) await tab.click();
      const box = page.getByLabel(`${artifactName} raw JSON`);
      if (!(await box.isVisible().catch(() => false))) {
        await page.getByRole("button", { name: /^Raw JSON$/ }).first().click(); // switch this artifact to raw JSON
      }
      await box.waitFor({ timeout: 10_000 });
      await box.fill(JSON.stringify(value, null, 2));
    }
  }

  // A comment is required on approve_actions gates (and harmless elsewhere) — fill it if present.
  const comment = page.getByPlaceholder(/comment is required|Optional context/i);
  if (await comment.isVisible().catch(() => false)) await comment.fill("e2e approval");

  await page.getByRole("button", { name: submitName }).first().click();
  // Real success signal: the decision was recorded → every action control is gone (task now decided).
  await expect(page.getByRole("button", { name: new RegExp(`${submitName.source}|^Claim task$`) }))
    .toHaveCount(0, { timeout: 25_000 });
}
