import { test, expect } from "../support/fixtures";
import { resolveTaskOnPage } from "../pages/screens";
import { scenario, interpolate } from "../support/scenarios";
import { withPersonaPage } from "../support/personaPage";
import type { Persona } from "../support/env";
import {
  cohortByCorrelation, fireScenario, instanceStatus, missingPacks, openTaskOn, personaForRole,
} from "../support/backend";

// The headline journey: fire the ACH scenario, then drive its HITL gates ENTIRELY through the Task-Inbox UI —
// each gate resolved by an SoD-correct persona (claim + author the manual gates' artifacts via the raw-JSON
// form) — until the cohort closes Released, asserted off the Cohorts screen. The external orchestrator
// (pega_stub) is fired over its API; discovering *which* gate is open + *who* may act (SoD) is plumbing; every
// claim/decide/form action happens in the browser.
test.describe("HITL via the Task Inbox → cohort closes (ACH)", () => {
  test.use({ persona: "priya" }); // the base page just reads the Cohorts screen; gates use per-persona pages
  test.setTimeout(260_000);

  test("credit_approve: gates resolved in the UI drive the cohort to closed/Released", async ({ page, browser }) => {
    const ach = scenario("ach_exposure");
    test.skip(!ach, "no ach_exposure scenario spec");
    const missing = await missingPacks(ach!);
    if (missing === null) test.skip(true, "registry /packs unreadable");
    if (missing && missing.length) test.skip(true, `onboard ${missing} first`);

    const correlation = await fireScenario(ach!);
    const outputs = ach!.hitl.outputs ?? {};
    const pool = (ach!.hitl.personas ?? ["marcus", "riya"]) as Persona[];
    const wantState = ach!.expect.cohort?.state ?? "closed";
    const wantOutcome = ach!.expect.cohort?.outcome;

    const deadline = Date.now() + 220_000;
    const seen = new Set<string>();
    while (Date.now() < deadline) {
      const cohort = await cohortByCorrelation(correlation);
      if (cohort?.state === wantState) break;
      for (const m of cohort?.roster ?? []) {
        const pid = m.process_instance_id;
        if (!pid || (await instanceStatus(pid)) !== "waiting_hitl") continue;
        const task = await openTaskOn(pid);
        if (!task || seen.has(task.task_id)) continue;
        seen.add(task.task_id);
        // Role-aware + SoD-correct actor: the persona who HOLDS this gate's role and isn't SoD-excluded (roles are
        // now distributed across riya/marcus per the pack SoD — see onboard_ach.py `_role_persona`).
        const persona = await personaForRole(pool, task.role, task.excluded);
        if (!persona) continue; // no eligible actor yet — retry next pass
        const edits = outputs[task.element_id] ? interpolate(outputs[task.element_id], { correlation }) : null;
        // Resolve THIS gate in the Task-Inbox detail, as that persona, through the UI.
        await withPersonaPage(browser, persona, async (p) => {
          await p.goto(`/inbox/${task.task_id}`);
          await resolveTaskOnPage(p, edits);
        });
      }
      await page.waitForTimeout(3000);
    }

    // Assert the OUTCOME from the Cohorts UI (not the API): the cohort detail shows Closed (+ Released).
    await page.goto(`/cohorts/by-correlation/${correlation}`);
    await expect(page.getByText(/Cohort state\s*closed/i).or(page.locator("text=/^Closed$/")).first())
      .toBeVisible({ timeout: 25_000 });
    if (wantOutcome) await expect(page.getByText(new RegExp(wantOutcome)).first()).toBeVisible();
    const final = await cohortByCorrelation(correlation);
    expect(final?.rollup?.failed ?? 0).toBe(0);
  });
});
