import { test, expect } from "../support/fixtures";
import { CohortDefinition } from "../pages/screens";
import { scenario } from "../support/scenarios";
import { missingPacks } from "../support/backend";

// Owner-gating on the SAME cohort-definition detail: priya (process-owner) sees the inline editor + DAG/SLA
// editor; marcus (non-owner) sees the read view only. Proven with two persona projects over one screen.
const DEF = "ach_exposure_cohort";

test.beforeEach(async () => {
  const ach = scenario("ach_exposure");
  if (ach) {
    const missing = await missingPacks(ach);
    if (missing && missing.length) test.skip(true, `onboard ${missing} first`);
  }
});

test.describe("owner sees the editor", () => {
  test.use({ persona: "priya" });
  test("priya sees Edit definition + the Expectation graph & SLAs card", async ({ page }) => {
    const def = new CohortDefinition(page);
    await def.open(DEF);
    await expect(page.getByRole("heading", { name: DEF })).toBeVisible();
    await expect(def.editBtn()).toBeVisible();
    await expect(def.graphCard()).toBeVisible();
  });
});

test.describe("non-owner is read-only", () => {
  test.use({ persona: "marcus" });
  test("marcus sees the definition read-only — no Edit control", async ({ page }) => {
    const def = new CohortDefinition(page);
    await def.open(DEF);
    await expect(page.getByRole("heading", { name: DEF })).toBeVisible();
    await expect(def.editBtn()).toHaveCount(0);
    await expect(def.graphCard()).toBeVisible(); // read view of the graph still shows
  });
});
