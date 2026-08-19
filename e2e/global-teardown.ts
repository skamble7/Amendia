// e2e/global-teardown.ts — leave the stack as found. ADR-061 clean-delete the deterministically-loaded ACH
// packs + the cohort definition (idempotent; only what setup created). Fired cases persist as closed cohort
// instances (observability rows) — those are tagged with the run id (see fireScenario) and are cleared by
// Sandeep's per-run DB reset; there is no cohort-instance delete API to call here.
//
// This is the DETERMINISTIC gate's teardown — it always runs (no keep flag). The copilot lifecycle command
// (tools/e2e-copilot.sh) uses a separate config with NO teardown, so it retains everything for inspection.
import { teardownAchDomain } from "./support/setup";

export default async function globalTeardown() {
  try {
    const r = teardownAchDomain();
    console.log(`\n[e2e] teardown:\n${r.out}\n`);
  } catch (e) {
    console.warn(`[e2e] teardown error (ignored): ${e}`);
  }
}
