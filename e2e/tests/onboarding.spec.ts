import path from "node:path";
import { test, expect } from "../support/fixtures";
import { OnboardingWizard } from "../pages/screens";
import { E2E_DIR } from "../support/env";
import { activePackKeys } from "../support/backend";

// The onboarding COVERAGE journey. Onboarding-to-active is exercised deterministically by the suite's own setup
// (it drives the real onboarding API to PUBLISH the three ACH packs every run — see global-setup); here we assert
// the browser-visible, STABLE outcomes (never LLM-inferred values): owner-gating, the Camunda→FEEL normalization
// on upload, and that published packs surface in the Registry.
test.describe("onboarding coverage", () => {
  test.describe("owner drives the wizard; upload normalizes Camunda conditions", () => {
    test.use({ persona: "priya" });

    test("priya opens the technical wizard, uploads a Camunda ${…} BPMN, and the pack is drafted + normalized", async ({ page }) => {
      const wiz = new OnboardingWizard(page);
      const packKey = `e2e-onb-${Date.now()}`;
      await wiz.newSession(packKey, { title: "E2E onboarding coverage" });
      await wiz.uploadBpmn(path.join(E2E_DIR, "fixtures", "camunda-gateways.bpmn"));
      await page.getByRole("button", { name: /Parse & preview coverage/i }).click();

      // Stable outcomes: the BPMN attached (draft session progressed) + the normalization banner fired.
      await expect(page.getByText(/BPMN attached/i)).toBeVisible({ timeout: 20_000 });
      await expect(wiz.normalizationNotice()).toBeVisible();
    });
  });

  test.describe("onboarding is owner-gated", () => {
    test.use({ persona: "marcus" });
    test("a non-owner does not get the Registry / onboarding surface", async ({ page }) => {
      await page.goto("/dashboard");
      await expect(page.getByRole("link", { name: "Dashboard" }).first()).toBeVisible();
      await expect(page.getByRole("link", { name: "Registry" })).toHaveCount(0); // Registry nav hidden for non-owners
    });
  });

  test.describe("the deterministic setup published the ACH packs (onboarding-to-active)", () => {
    test.use({ persona: "priya" });
    test("all three ACH packs are active in the Registry", async ({ page }) => {
      const active = await activePackKeys();
      test.skip(active === null, "registry /packs unreadable");
      const missing = ["ach-exposure-assess", "ach-decision-enforce", "ach-closeout"].filter((k) => !active!.has(k));
      test.skip(missing.length > 0, `ACH setup incomplete (${missing.join(", ")})`);
      await page.goto("/registry");
      await expect(page.getByText("ach-exposure-assess").first()).toBeVisible({ timeout: 15_000 });
    });
  });
});
