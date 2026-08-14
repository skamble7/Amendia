import { test, expect } from "../support/fixtures";
import { scenario } from "../support/scenarios";
import { fireScenario, missingPacks } from "../support/backend";

// Live SSE: with the Instances list open and NOT reloaded, firing a case makes a new instance row arrive live
// (the notification-service relays dispatch_accepted → the browser invalidates ["instances"] → refetch). Only a
// browser can prove the SSE-signal → refetch path; we assert with expect.poll (auto-wait), no fixed sleeps.
test.describe("live SSE instance update", () => {
  test.use({ persona: "priya" });
  test.setTimeout(150_000);

  test("a fired case's instance appears on the Instances list without a reload", async ({ page }) => {
    const ach = scenario("ach_exposure");
    test.skip(!ach, "no ach_exposure scenario spec");
    const missing = await missingPacks(ach!);
    if (missing && missing.length) test.skip(true, `onboard ${missing} first`);

    await page.goto("/instances");
    await expect(page.getByRole("heading", { name: /Instances/i }).first()).toBeVisible();
    const rowsBefore = await page.getByRole("row").count();

    // Fire AFTER the page is loaded; do NOT navigate/reload — the new instance must arrive via SSE → refetch.
    await fireScenario(ach!);
    await expect
      .poll(async () => page.getByRole("row").count(), { timeout: 120_000, intervals: [2000] })
      .toBeGreaterThan(rowsBefore);
  });
});
