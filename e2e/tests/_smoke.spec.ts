import { test, expect } from "../support/fixtures";

test.describe("harness smoke (login + persona + nav)", () => {
  test("priya lands authenticated and sees the nav", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByRole("link", { name: "Cohorts" }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: "Registry" })).toBeVisible(); // owner-only nav → proves priya's roles
  });
});
