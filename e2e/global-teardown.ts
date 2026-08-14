// e2e/global-teardown.ts — leave the stack as found. ADR-061 clean-delete the deterministically-loaded ACH
// packs + the cohort definition (idempotent; only what setup created). Fired cases persist as closed cohort
// instances (observability rows) — those are tagged with the run id (see fireScenario) and are cleared by
// Sandeep's per-run DB reset; there is no cohort-instance delete API to call here.
import { teardownAchDomain } from "./support/setup";
import { KEEP_STACK } from "./support/env";

export default async function globalTeardown() {
  if (KEEP_STACK) {
    console.log("\n[e2e] keeping onboarded stack (E2E_KEEP set) — packs/cohort/roles/data left in place\n");
    return;
  }
  try {
    const r = teardownAchDomain();
    console.log(`\n[e2e] teardown:\n${r.out}\n`);
  } catch (e) {
    console.warn(`[e2e] teardown error (ignored): ${e}`);
  }
}
