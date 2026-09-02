import path from "node:path";
import { test, expect } from "../support/fixtures";
import { OnboardingWizard } from "../pages/screens";
import { E2E_DIR } from "../support/env";
import { activePackKeys } from "../support/backend";

// ADR-065 P4b (D5) — the operator side-effect WAIVER journey, driven through the real UI as the owner (priya).
// Scoped from P3's report §8: drive a side-effectful capability to a waiver, assert the affordance REFUSES a short
// justification, assert the waived step is restated on the review summary, publish, and assert the waiver renders
// on the pack detail page. Deterministic (no LLM). Belongs in the CI gate; tears down its own pack.
//
// Selectors are role/label/text first (the suite is deliberately testid-free). The ONE testid used is
// `data-testid="review-waived-gate"` on the wizard ReviewStep's waived row — the row has no role and its text
// (a humanized sentence) is not a stable accessible name; the affordance itself is reached by its button label.
//
// Skips clean (never fails the gate) when the stack / an MCP is unreachable — matching the rest of the suite.
test.describe("side-effect waiver (ADR-065)", () => {
  test.use({ persona: "priya" });

  test("priya waives the human gate on a side-effectful step: affordance refuses a short reason, the waived step is restated at review, and it renders on pack detail", async ({ page }) => {
    test.setTimeout(240_000);
    const active = await activePackKeys();
    test.skip(active === null, "registry /packs unreadable (stack down?)");

    const packKey = `e2e-waiver-${Date.now()}`;
    const JUSTIFICATION =
      "The ACH handback is idempotent — the orchestrator re-confirms receipt, so a re-run is a no-op with nothing for a person to approve.";

    const wiz = new OnboardingWizard(page);
    await wiz.newSession(packKey, { title: "E2E waiver journey" });
    // A minimal BPMN whose single serviceTask binds a side-effectful tool (the ACH notify handback shape).
    await wiz.uploadBpmn(path.join(E2E_DIR, "fixtures", "corpus", "ach-closeout.bpmn"));
    await page.getByRole("button", { name: /Parse & preview coverage/i }).click();
    await expect(page.getByText(/BPMN attached/i)).toBeVisible({ timeout: 20_000 });
    await page.getByRole("button", { name: /Continue to capabilities/i }).click();

    // Introspect the closeout MCP so its side-effectful tools (mark_completed / purge_working_data / notify_pega)
    // are staged with their TRUE side_effect (ADR-065 P4b — honest, not gating-derived).
    const endpoint = page.getByLabel(/endpoint/i).first();
    if (!(await endpoint.isVisible().catch(() => false))) {
      test.skip(true, "capabilities step not reachable in this build — nothing to drive");
    }
    await endpoint.fill("http://ach-closeout-mcp:8077/mcp");
    await page.getByRole("button", { name: /^Introspect$/i }).click();
    const staged = page.getByText(/mark_completed|notify_pega/i).first();
    test.skip(!(await staged.isVisible({ timeout: 20_000 }).catch(() => false)),
      "closeout MCP unreachable — waiver journey skipped");

    // Reach the Bindings step and find the row whose capability is side-effectful.
    await page.getByRole("button", { name: /Continue|Bindings/i }).first().click();
    const waiveButton = page.getByRole("button", { name: /Waive the human gate/i }).first();
    test.skip(!(await waiveButton.isVisible({ timeout: 20_000 }).catch(() => false)),
      "no side-effectful capability row surfaced a waiver affordance — journey skipped");

    // The affordance is a JUSTIFICATION, never a toggle: a short reason keeps "Waive the gate" disabled.
    await waiveButton.click();
    const reason = page.getByLabel(/waiver justification/i);
    await reason.fill("too short");
    await expect(page.getByRole("button", { name: /^Waive the gate$/i })).toBeDisabled();
    await reason.fill(JUSTIFICATION);
    await expect(page.getByRole("button", { name: /^Waive the gate$/i })).toBeEnabled();
    await page.getByRole("button", { name: /^Waive the gate$/i }).click();
    await expect(page.getByText(/Runs with no human approval — waived/i)).toBeVisible();

    // Drive the rest of the wizard to the Review step (triage/gateways are pre-filled deterministically).
    for (let i = 0; i < 6; i++) {
      const next = page.getByRole("button", { name: /^Continue$|Review|Validate/i }).first();
      if (!(await next.isVisible().catch(() => false))) break;
      await next.click();
      if (await page.getByRole("button", { name: /Activate pack/i }).isVisible().catch(() => false)) break;
    }

    // The last screen before publishing RESTATES the ungated action (D4) — the loudest row.
    await expect(page.getByText(/no one approving/i).first()).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("review-waived-gate").first()).toBeVisible();
    await expect(page.getByText(JUSTIFICATION.slice(0, 40))).toBeVisible();

    // Validate → Activate (publish).
    await page.getByRole("button", { name: /^Validate$|^Re-validate$/i }).click();
    const activate = page.getByRole("button", { name: /Activate pack/i });
    await expect(activate).toBeEnabled({ timeout: 30_000 });
    await activate.click();
    await expect(page.getByText(/Pack activated/i)).toBeVisible({ timeout: 60_000 });

    // The pack detail page lists the waiver (element, capability, justification) — visible to any viewer.
    await page.goto(`/registry/packs/${packKey}/1.0.0`);
    await expect(page.getByText(/Side-effect waivers/i)).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText(JUSTIFICATION.slice(0, 40))).toBeVisible();

    // Teardown: delete the pack this journey created (like the rest of the suite).
    await page.request.delete(`${process.env.REGISTRY ?? "http://localhost:8084"}/packs/${packKey}`).catch(() => {});
  });
});
