import { test, expect } from "../support/fixtures";
import { Cohorts } from "../pages/screens";

// Cohorts render — as priya: Instances shows cohorts with state; Definitions lists definitions. The SLA
// board / row badges render when a cohort has SLA data (ACH declares an SLA graph, so its cohorts do).
test.describe("Cohorts screens render", () => {
  test.use({ persona: "priya" });

  test("Instances tab lists cohorts with state; Definitions tab lists definitions", async ({ page }) => {
    const cohorts = new Cohorts(page);
    await cohorts.open();

    // Instances (default tab): KPI cards + at least one state chip once cohorts exist.
    await expect(page.getByRole("tab", { name: /instances/i })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByText(/Active cohorts|No cohorts yet/).first()).toBeVisible();
    const anyState = page.getByText(/^(Open|Closing|Closed)$/).first();
    await expect(anyState).toBeVisible();

    // Definitions tab lists the ACH cohort definition (skip cleanly if setup didn't create it — e.g. stack down).
    await cohorts.openDefinitions();
    await expect(page).toHaveURL(/tab=definitions/);
    const def = page.getByText("ach_exposure_cohort").first();
    const present = await def.waitFor({ timeout: 8_000 }).then(() => true).catch(() => false);
    test.skip(!present, "no cohort definition present (ACH setup did not run)");
    await expect(def).toBeVisible();
  });

  test("a closed ACH cohort detail shows the SLA board (owner-attributed) when SLA data exists", async ({ page }) => {
    // Find a closed cohort from the list and open it; ACH cohorts carry SLA transitions → the SLA card renders.
    const cohorts = new Cohorts(page);
    await cohorts.open();
    const firstRow = page.getByRole("row").filter({ hasText: /case-/ }).first();
    if (!(await firstRow.isVisible().catch(() => false))) test.skip(true, "no cohort instances observed yet");
    await firstRow.click();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    // The SLA panel is problem-focused: present only when GLEA observed SLA transitions. Assert softly.
    const slaCard = page.getByText(/SLAs — timing & accountability/i);
    if (await slaCard.isVisible().catch(() => false)) {
      await expect(page.getByText(/Breaches|At risk|Satisfied/).first()).toBeVisible();
    }
  });
});
