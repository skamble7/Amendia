import { test, expect } from "../support/fixtures";
import { CohortDefinition } from "../pages/screens";

// The owner-gated DAG/SLA editor (forward-only). Two angles, no production mutation:
//  (A) a throwaway definition → build a graph, Save; an invalid graph surfaces the server 422 inline; a valid
//      one round-trips into the read view.
//  (B) the real ACH definition (has instances) → Edit shows the forward-only warning + the editor; Cancel.
test.describe("DAG/SLA editor", () => {
  test.use({ persona: "priya" });

  const CLOSE_SCHEMA = JSON.stringify({
    type: "object", required: ["event", "case_id"],
    properties: { event: { const: "process_completed" }, case_id: { type: "string" } },
  });

  test("build + save a graph on a throwaway definition; invalid graph is blocked with the server message", async ({ page }) => {
    const defId = `e2e_sla_${Date.now()}`;
    // Register a throwaway cohort definition via the New-cohort UI.
    await page.goto("/cohorts/new");
    await page.locator("#coh-id").fill(defId);
    const schema = page.locator("#coh-schema");
    await schema.fill(CLOSE_SCHEMA);
    await page.locator("#coh-corr").fill("case_id");
    await page.getByRole("button", { name: /Register cohort/i }).click();
    // Register navigates back to the cohorts list; open the new definition's detail to edit its graph.
    await expect(page).toHaveURL(/\/cohorts(\?|$)/, { timeout: 20_000 });

    const def = new CohortDefinition(page);
    await def.open(defId);
    await expect(page.getByRole("heading", { name: defId })).toBeVisible({ timeout: 15_000 });
    await def.startEdit();
    // Add a node but NO edges → unreachable from __start__ → server 422, surfaced inline.
    await def.addNode("seg-a");
    await def.saveBtn().click();
    await expect(page.getByText(/expectation_graph invalid|not reachable|orphan|dead-end/i)).toBeVisible({ timeout: 15_000 });

    // Now wire it: __start__ → seg-a → __close__, and Save → success; read view reflects the node.
    await def.addEdge();
    await page.getByLabel("edge 0 to").selectOption("seg-a").catch(() => {});
    await def.addEdge();
    await page.getByLabel("edge 1 from").selectOption("seg-a").catch(() => {});
    await page.getByLabel("edge 1 to").selectOption("__close__").catch(() => {});
    await def.saveBtn().click();
    await expect(def.editBtn()).toBeVisible({ timeout: 15_000 }); // back to read view (Edit returns)
    await expect(page.getByText("seg-a").first()).toBeVisible();
  });

  test("editing the real ACH definition shows the forward-only warning + editor (then cancel, no mutation)", async ({ page }) => {
    const def = new CohortDefinition(page);
    await def.open("ach_exposure_cohort");
    const present = await page.getByRole("heading", { name: "ach_exposure_cohort" })
      .waitFor({ timeout: 12_000 }).then(() => true).catch(() => false);
    test.skip(!present, "ach_exposure_cohort not present");
    await def.editBtn().waitFor({ timeout: 15_000 });
    await def.startEdit();
    await expect(page.getByText(/forward-only/i).first()).toBeVisible();
    await expect(page.getByRole("button", { name: /Add edge/i })).toBeVisible(); // the DAG/SLA editor is live
    await page.getByRole("button", { name: /^Cancel$/i }).click();               // no save → no mutation
    await expect(def.editBtn()).toBeVisible();
  });
});
