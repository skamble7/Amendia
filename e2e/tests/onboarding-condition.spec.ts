import path from "node:path";
import { test, expect } from "../support/fixtures";
import { OnboardingWizard } from "../pages/screens";
import { E2E_DIR } from "../support/env";

// Condition hardening in the UI: uploading a Camunda `${…}` BPMN in the onboarding wizard shows the
// normalization banner (Camunda→FEEL, before/after). This is the visible proof of the shipped hardening.
test.describe("onboarding wizard — condition normalization banner", () => {
  test.use({ persona: "priya" }); // Registry/onboarding is process-owner gated

  test("uploading a Camunda ${…} BPMN surfaces the normalization notice", async ({ page }) => {
    const wiz = new OnboardingWizard(page);
    const packKey = `e2e-cond-${Date.now()}`;
    await wiz.newSession(packKey, { title: "E2E condition probe" });

    await wiz.uploadBpmn(path.join(E2E_DIR, "fixtures", "camunda-gateways.bpmn"));
    await page.getByRole("button", { name: /Parse & preview coverage/i }).click();

    // The banner (informational, non-blocking) names how many conditions were auto-converted.
    await expect(wiz.normalizationNotice()).toBeVisible({ timeout: 20_000 });
    await wiz.normalizationNotice().click(); // expand the <details> to the per-flow before/after
    await expect(page.getByText('${decision == "Proceed"}', { exact: true })).toBeVisible(); // before (raw)
    await expect(page.getByText('decision == "Proceed"', { exact: true })).toBeVisible();   // after (canonical)
  });
});
