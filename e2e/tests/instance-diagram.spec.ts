import { test, expect } from "../support/fixtures";
import { closedCohortCorrelation } from "../support/backend";

// Per-member BPMN diagram highlighting (ADR-062): open a closed cohort; each member segment renders its own
// BPMN diagram highlighted to its execution, with the executed/current/not-taken/failed legend. The cohort is
// discovered via the API (plumbing) and opened + asserted in the browser.
test.describe("member diagram highlighting (ADR-062)", () => {
  test.use({ persona: "priya" });

  test("a closed cohort renders highlighted per-member BPMN diagrams", async ({ page }) => {
    const correlation = await closedCohortCorrelation();
    test.skip(!correlation, "no closed cohort observed yet");
    await page.goto(`/cohorts/by-correlation/${correlation}`);
    await expect(page.getByText(/Member processes — live state/i)).toBeVisible({ timeout: 20_000 });
    // bpmn-js SVG mounted + the ADR-062 highlight legend.
    await expect(page.locator("svg").first()).toBeVisible({ timeout: 25_000 });
    await expect(page.getByText(/executed \(done\)/i)).toBeVisible();
  });
});
