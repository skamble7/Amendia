import { test, expect } from "../support/fixtures";
import { resolveTaskOnPage } from "../pages/screens";
import { scenario, interpolate, type Scenario } from "../support/scenarios";
import { withPersonaPage } from "../support/personaPage";
import type { Persona } from "../support/env";
import {
  cohortByCorrelation, cohortDefinition, cohortOutcome, cohortSla, fireScenario, instanceStatus,
  missingPacks, openTaskOn, packManifest, personaForRole,
} from "../support/backend";

// ── ACH full-lifecycle flagship acceptance journey ───────────────────────────────────────────────────────────
// The ach_exposure worked example end-to-end, FAITHFUL to the BPMNs + Amendia's rule that ANY side-effectful
// activity is human-gated: priya onboards the 3 segments (each side-effectful action tool `approve_actions`-gated —
// A's notify_pega handback, B's prepare_release/request_purge/notify, C's mark_completed/purge/notify — plus the
// AuthorizeRelease/Purge + ReviewArtifacts decision userTasks) and owns the cohort, then steps out. Access is
// distributed to TWO distinct humans by role (Marcus → enforce/B; Riya → assess/A + closeout/C); the runtime AND UI
// enforce role-holding at claim. pega_stub fires A → B → C on each notify handback, so every gate must be driven for
// the cohort to advance. We drive EVERY gate through the Task Inbox as its role-holder and assert the cohort reaches
// MEMBERS = 3 (assess+enforce+closeout all joined & terminal) and closes — a 1-member / stalled cohort FAILS. Three
// flows: credit_approve → Released, debit_reject → Purged, late_closeout → enforce→closeout SLA breach (external),
// still Released. Assert STABLE OUTCOMES only (role distribution, membership, terminal/cohort/SLA) — never inferred
// values.

const POOL: Persona[] = ["marcus", "riya"];
const SEGMENTS = ["ach-exposure-assess", "ach-decision-enforce", "ach-closeout"];

// Human-gate artifact edits per branch (keyed by element_id, {correlation} interpolated) — the ONLY non-derivable
// inputs (human outputs a "complete" can't synthesize). Mirrors backend/tests/smoke/scenarios/ach_exposure.yaml.
const RELEASE_OUT: Record<string, Record<string, unknown>> = {
  Task_AuthorizeRelease: { release_authorization: { authorized: true, case_id: "{correlation}", company: "ACME-LOGISTICS", decision: {}, records: [] } },
  Task_ReviewArtifacts: { review_decision: { approved: true, disposition_confirmed: "released" } },
};
const PURGE_OUT: Record<string, Record<string, unknown>> = {
  Task_AuthorizePurge: { purge_authorization: { authorized: true, case_id: "{correlation}" } },
  Task_ReviewArtifacts: { review_decision: { approved: true, disposition_confirmed: "purged" } },
};

/** Build a flow variant of the base ach_exposure scenario (pega_stub scenario + expected outcome + human outputs). */
function flow(base: Scenario, pegaScenario: string, outputs: Record<string, Record<string, unknown>>, outcome: string): Scenario {
  return {
    ...base,
    trigger: { kind: "pega_stub", request: { scenario: pegaScenario } },
    hitl: { ...base.hitl, personas: POOL, outputs },
    expect: { cohort: { state: "closed", outcome } },
  };
}

/** The gate role a pack binding declares for an element — read from the committed manifest (`hitl.role`, the human
 * executor's `executor.role` as a fallback). */
function gateRole(manifest: Record<string, unknown> | null, elementId: string): string | null {
  const bindings = (manifest?.bindings ?? []) as { element_id?: string; hitl?: { role?: string }; executor?: { role?: string } }[];
  const b = bindings.find((x) => x.element_id === elementId);
  return b?.hitl?.role ?? b?.executor?.role ?? null;
}

/** REUSE the hitl-arc loop (role-aware): poll the cohort roster → find each open gate → resolve it in the UI as the
 * persona who HOLDS the gate role and isn't SoD-excluded. Returns the final cohort. No fixed sleeps beyond the poll. */
async function driveToClose(browser: import("@playwright/test").Browser, page: import("@playwright/test").Page,
  sc: Scenario, correlation: string): Promise<Awaited<ReturnType<typeof cohortByCorrelation>>> {
  const outputs = sc.hitl.outputs ?? {};
  const wantState = sc.expect.cohort?.state ?? "closed";
  const deadline = Date.now() + 240_000;
  const seen = new Set<string>();
  while (Date.now() < deadline) {
    const cohort = await cohortByCorrelation(correlation);
    if (cohort?.state === wantState) return cohort;
    for (const m of cohort?.roster ?? []) {
      const pid = m.process_instance_id;
      if (!pid || (await instanceStatus(pid)) !== "waiting_hitl") continue;
      const task = await openTaskOn(pid);
      if (!task || seen.has(task.task_id)) continue;
      seen.add(task.task_id);
      const persona = await personaForRole(POOL, task.role, task.excluded); // SoD-correct + role-holding actor
      if (!persona) continue; // no eligible actor yet — retry next pass
      const edits = outputs[task.element_id] ? interpolate(outputs[task.element_id], { correlation }) : null;
      await withPersonaPage(browser, persona as Persona, async (p) => {
        await p.goto(`/inbox/${task.task_id}`);
        await resolveTaskOnPage(p, edits);
      });
    }
    await page.waitForTimeout(3000);
  }
  return cohortByCorrelation(correlation);
}

/** THE assertion that catches a stall: the cohort must reach ALL 3 members joined + terminal (done), closed, with the
 * expected outcome. A cohort stuck at 1 member (a segment that never handed back) never satisfies this → the test
 * fails (rather than a bare "closed" that a 1-member cohort could never reach anyway). */
async function assertThreeMembersClosed(correlation: string, outcome: string): Promise<void> {
  await expect
    .poll(async () => {
      const c = await cohortByCorrelation(correlation);
      return {
        members: c?.member_count ?? c?.roster?.length ?? 0,
        done: c?.rollup?.done ?? 0, running: c?.rollup?.running ?? 0, failed: c?.rollup?.failed ?? 0,
        state: c?.state,
      };
    }, { timeout: 20_000, message: `cohort ${correlation} must reach 3 joined+terminal members and close (a 1-member stall fails here)` })
    .toEqual({ members: 3, done: 3, running: 0, failed: 0, state: "closed" });
  expect(await cohortOutcome(correlation), `cohort outcome should be ${outcome}`).toBe(outcome);
}

test.describe("ACH full lifecycle — onboard → SoD access → cohort/DAG/SLA → multi-flow (incl. SLA breach)", () => {
  test.use({ persona: "priya" });

  // Degrade to a clean skip when the stack/packs aren't ready (never a red).
  test.beforeEach(async () => {
    const base = scenario("ach_exposure");
    if (!base) { test.skip(true, "no ach_exposure scenario spec"); return; }
    const missing = await missingPacks(base);
    if (missing === null) { test.skip(true, "registry /packs unreadable (stack down?)"); return; }
    if (missing.length) { test.skip(true, `ACH packs not onboarded: ${missing.join(", ")}`); return; }
  });

  // ── Every side-effectful action is human-gated (faithful), and access is split across two distinct humans ──────
  test("each segment gates its side-effectful action tools, and the enforce approver ≠ the assess/closeout reviewer", async () => {
    // FAITHFUL GATING — the side-effectful ACTION tools carry approve_actions gates (Amendia gates any side effect).
    const gatedActions: Record<string, string[]> = {
      "ach-exposure-assess": ["Task_NotifyAssessed"],
      "ach-decision-enforce": ["Task_PrepareRelease", "Task_RequestPurge", "Task_NotifyOrchestrated"],
      "ach-closeout": ["Task_MarkCompleted", "Task_PurgeWorkingData", "Task_NotifyClosedOut"],
    };
    for (const [pack, els] of Object.entries(gatedActions)) {
      const m = await packManifest(pack);
      expect(m, `${pack} manifest`).toBeTruthy();
      const bindings = (m!.bindings ?? []) as { element_id?: string; hitl?: { mode?: string } }[];
      for (const el of els) {
        const b = bindings.find((x) => x.element_id === el);
        expect(b?.hitl?.mode, `${pack}/${el} must be an approve_actions gate (its tool is side-effectful)`).toBe("approve_actions");
      }
    }

    // TWO DISTINCT HUMANS — gate roles read from the packs (not hardcoded); the enforce APPROVER (B) is a different
    // person from the assess (A) and closeout (C) REVIEWER. priya only onboards; Marcus and Riya carry the process.
    // Poll: a freshly-granted role can take up to ~30s to become visible (amendia_auth's (iss,sub) resolve-cache).
    const enforceRole = gateRole(await packManifest("ach-decision-enforce"), "Task_AuthorizeRelease");
    const assessRole = gateRole(await packManifest("ach-exposure-assess"), "Task_NotifyAssessed");
    const closeoutRole = gateRole(await packManifest("ach-closeout"), "Task_ReviewArtifacts");
    expect(enforceRole && assessRole && closeoutRole, "each segment declares its gate role").toBeTruthy();
    await expect
      .poll(async () => {
        const [e, a, c] = await Promise.all([
          personaForRole(POOL, enforceRole!, []), personaForRole(POOL, assessRole!, []), personaForRole(POOL, closeoutRole!, []),
        ]);
        return (!!e && !!a && !!c && e !== a && e !== c) ? "distinct" : `enforce=${e} assess=${a} closeout=${c}`;
      }, { timeout: 45_000, message: "each gate role must have a holder AND the enforce approver ≠ the assess/closeout reviewer" })
      .toBe("distinct");
  });

  // ── The cohort definition has all three pack members (Members 3) ───────────────────────────────────────────
  test("the ach_exposure_cohort definition has all three pack members (Members 3)", async () => {
    const members: string[] = [];
    for (const key of SEGMENTS) {
      const m = await packManifest(key);
      const cm = (m?.cohort_membership as { cohort_def_id?: string } | undefined);
      if (cm?.cohort_def_id === "ach_exposure_cohort") members.push(key);
    }
    expect(members, "all three ACH packs must declare membership in ach_exposure_cohort").toEqual(SEGMENTS);
  });

  // ── The cohort DAG + enforce→closeout SLA (owner=external, the breach target) ───────────────────────────────
  test("the ach_exposure cohort declares the assess→enforce→closeout DAG + the enforce→closeout arrival SLA", async () => {
    const def = await cohortDefinition("ach_exposure_cohort");
    expect(def, "ach_exposure_cohort definition").toBeTruthy();
    const graph = ((def!.expectation_graph ?? def) as { nodes?: { node_id: string }[]; edges?: { from_node: string; to_node: string; sla?: { owner?: string; satisfy_moment?: string } }[] });
    const nodeIds = (graph.nodes ?? []).map((n) => n.node_id);
    for (const seg of ["ach-exposure-assess", "ach-decision-enforce", "ach-closeout"]) expect(nodeIds).toContain(seg);
    const slaEdge = (graph.edges ?? []).find((e) => e.from_node === "ach-decision-enforce" && e.to_node === "ach-closeout" && e.sla);
    expect(slaEdge, "enforce→closeout edge must carry an arrival SLA (the breach target)").toBeTruthy();
    expect(slaEdge!.sla!.owner).toBe("external");
  });

  // ── Flow 1: credit_approve → release branch → 3 members, closed / Released ──────────────────────────────────
  test("credit_approve: A auto-runs+notify (Riya) → B AuthorizeRelease+actions (Marcus) → C review+actions (Riya) → 3 members, Released", async ({ page, browser }) => {
    test.setTimeout(300_000);
    const sc = flow(scenario("ach_exposure")!, "credit_approve", RELEASE_OUT, "Released");
    let correlation: string;
    try { correlation = await fireScenario(sc); } catch (e) { test.skip(true, `pega_stub unavailable: ${e}`); return; }

    await driveToClose(browser, page, sc, correlation);
    await assertThreeMembersClosed(correlation, "Released"); // MEMBERS=3 joined+terminal+closed — a 1-member stall fails

    await page.goto(`/cohorts/by-correlation/${correlation}`);
    await expect(page.getByText(/Cohort state\s*closed/i).or(page.locator("text=/^Closed$/")).first()).toBeVisible({ timeout: 25_000 });
    await expect(page.getByText(/Released/).first()).toBeVisible();
  });

  // ── Flow 2: debit_reject → purge branch → 3 members, closed / Purged ────────────────────────────────────────
  test("debit_reject: B AuthorizePurge+request_purge (Marcus) → C (Riya) → 3 members, Purged", async ({ page, browser }) => {
    test.setTimeout(300_000);
    const sc = flow(scenario("ach_exposure")!, "debit_reject", PURGE_OUT, "Purged");
    let correlation: string;
    try { correlation = await fireScenario(sc); } catch (e) { test.skip(true, `pega_stub unavailable: ${e}`); return; }

    await driveToClose(browser, page, sc, correlation);
    await assertThreeMembersClosed(correlation, "Purged"); // MEMBERS=3 joined+terminal+closed

    await page.goto(`/cohorts/by-correlation/${correlation}`);
    await expect(page.getByText(/Cohort state\s*closed/i).or(page.locator("text=/^Closed$/")).first()).toBeVisible({ timeout: 25_000 });
    await expect(page.getByText(/Purged/).first()).toBeVisible();
  });

  // ── Flow 3: late_closeout → enforce→closeout arrival SLA BREACHES (owner=external), case still closes Released ─
  test("late_closeout: the enforce→closeout arrival SLA breaches (external), and the case still closes Released", async ({ page, browser }) => {
    test.setTimeout(360_000); // includes the ~25s deliberate closeout delay that breaches the 20s SLA
    const sc = flow(scenario("ach_exposure")!, "late_closeout", RELEASE_OUT, "Released");
    let correlation: string;
    try { correlation = await fireScenario(sc); } catch (e) { test.skip(true, `pega_stub unavailable: ${e}`); return; }

    await driveToClose(browser, page, sc, correlation);
    await assertThreeMembersClosed(correlation, "Released"); // 3 members joined+terminal+closed despite the breach

    // SLA breach (GLEA): an EXTERNAL-owner breach on the enforce→closeout edge (the orchestrator delivered the
    // closeout trigger late, so the external party owns the miss).
    await expect.poll(async () => (await cohortSla(correlation))?.breaches?.external ?? 0,
      { timeout: 30_000, message: "expected an external-owner SLA breach" }).toBeGreaterThanOrEqual(1);
    const sla = await cohortSla(correlation);
    expect(sla?.states?.some((s) => s.owner === "external" && s.state === "breached"), "a breached, external-owned SLA state").toBe(true);

    // SLA breach (UI): the cohort SLA board attributes the breach to the external owner.
    await page.goto(`/cohorts/by-correlation/${correlation}`);
    await expect(page.getByText(/SLAs — timing & accountability/i)).toBeVisible({ timeout: 25_000 });
    await expect(page.getByText(/Breaches by owner:/i)).toBeVisible();
    await expect(page.getByText(/external:\s*[1-9]/i)).toBeVisible();
    await expect(page.getByLabel(/sla state: Breached/i).first().or(page.getByText(/^Breached$/).first())).toBeVisible();
  });
});
