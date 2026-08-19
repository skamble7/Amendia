import path from "node:path";
import { test, expect } from "../support/fixtures";
import { E2E_DIR, type Persona } from "../support/env";
import { resolveTaskOnPage } from "../pages/screens";
import { withPersonaPage } from "../support/personaPage";
import {
  activePackKeys, cohortByCorrelation, cohortDefinition, cohortOutcome, cohortSla, fireScenario,
  instanceStatus, openTaskOn, packManifest, personaForRole, personaRoles,
} from "../support/backend";
import {
  cohortDefinitionExists, createCohortDefinition, grantRole, packGateRoles, putCohortMembership,
  synthesizeManualGateEdits, triggerSchema,
} from "../support/copilot";
import type { Scenario } from "../support/scenarios";

// ── ACH COPILOT lifecycle — the real-LLM onboarding path, end to end ────────────────────────────────────────────
// NON-BLOCKING (own command: tools/e2e-copilot.sh). priya drives the REAL copilot autopilot (/registry/onboard) to
// onboard the 3 ACH segments, then the same ach_exposure lifecycle the deterministic gate proves — cohort formation,
// SoD access, DAG+SLA, and the 3 pega flows — but over COPILOT-INFERRED packs. Because the copilot infers pack
// structure per run (role names, human-artifact schemas, gate shapes all vary), EVERYTHING is read from the live
// packs at runtime and NOTHING inferred is asserted or hardcoded. The manual-gate values are SYNTHESIZED from each
// gate's inferred artifact schema (the de-risk's 422 fix), and — because the copilot often infers a 4-eyes SoD
// within enforce that a single approver can't satisfy — every gate role is granted to BOTH marcus and riya and each
// gate is driven by the SoD-aware picker (marcus primary; riya provides the second signature). Retains everything
// (no teardown). Skips cleanly when the stack has no copilot model (502 copilot_llm_unavailable). See
// ach_copilot_derisk_findings.md.

const POOL: Persona[] = ["marcus", "riya"];
// Distinct from the deterministic gate's `ach_exposure_cohort` so the two commands never collide on a shared cohort
// definition (the copilot command retains its def; reusing the gate's id would break a later gate run on the same
// un-wiped stack). This command owns `ach_copilot_cohort` end to end.
const COHORT_DEF = "ach_copilot_cohort";
const STAMP = Date.now().toString(36); // fresh pack names per run (the runtime bundle-cache never evicts — de-risk)

interface SegCfg { seg: "assess" | "enforce" | "closeout"; bpmn: string; mcp: string; triggerFile: string; req: string }
const SEGS: SegCfg[] = [
  { seg: "assess", bpmn: "ach-exposure-assess.bpmn", mcp: "http://ach-assess-mcp:8075/mcp",
    triggerFile: "art.ach.assess_exposure_requested.json", req: "AssessExposureRequested" },
  { seg: "enforce", bpmn: "ach-decision-enforce.bpmn", mcp: "http://ach-enforce-mcp:8076/mcp",
    triggerFile: "art.ach.enforce_decision_requested.json", req: "EnforceDecisionRequested" },
  { seg: "closeout", bpmn: "ach-closeout.bpmn", mcp: "http://ach-closeout-mcp:8077/mcp",
    triggerFile: "art.ach.closeout_requested.json", req: "CloseoutRequested" },
];
const packKey = (seg: string) => `ach-copilot-${seg}-${STAMP}`;
const corpusBpmn = (f: string) => path.resolve(E2E_DIR, "../backend/docs/methodology/worked-examples/ach_exposure", f);

// Module state, shared across the serial tests. `ready` gates the flow tests: if onboarding/setup can't complete
// (no model, dirty stack, structural failure), the flows skip with the reason rather than red-failing on no packs.
let ready: { ok: boolean; reason?: string } = { ok: false, reason: "setup did not run" };

/** Drive the real copilot autopilot for one segment through the UI: upload → LLM draft → accept as-is → publish.
 *  Returns "published", or "skip" when the model is absent (502). Throws on a genuine publish failure. */
async function onboardSegment(page: import("@playwright/test").Page, cfg: SegCfg): Promise<"published" | "skip"> {
  const pk = packKey(cfg.seg);
  await page.goto("/registry/onboard");
  await page.getByLabel("BPMN file").setInputFiles(corpusBpmn(cfg.bpmn));
  await page.locator("#mcp").fill(cfg.mcp);
  await page.locator("#title").fill(`ACH copilot ${cfg.seg}`);
  await page.locator("#pk").fill(pk);
  // Paste the CORPUS trigger json_schema (recognised as a schema — has `properties`) so the copilot derives a
  // faithful trigger + the triage picker offers the real fields; this is the fidelity input that let the de-risk
  // chain case_id A→B. Triage: request_type == <req>.
  await page.getByLabel("Trigger event or schema").fill(JSON.stringify(triggerSchema(cfg.triggerFile), null, 2));
  await page.getByRole("button", { name: /Add rule/i }).click();
  await page.getByLabel("Trigger field").selectOption("request_type");
  await page.getByLabel("Operator").selectOption("eq");
  await page.getByLabel("Value").fill(cfg.req);

  await expect(page.getByRole("button", { name: /Generate process/i })).toBeEnabled();
  await page.getByRole("button", { name: /Generate process/i }).click();

  const reviewHeading = page.getByRole("heading", { name: /Review your process/i });
  const noModel = page.getByText(/isn't reachable right now/i);
  const hardError = page.getByText(/couldn't generate this process|Couldn't reach the service|Something went wrong generating/i);
  await expect(reviewHeading.or(noModel).or(hardError)).toBeVisible({ timeout: 180_000 });
  if (await noModel.isVisible().catch(() => false)) return "skip";
  if (await hardError.isVisible().catch(() => false)) {
    throw new Error(`copilot generate failed (${cfg.seg}, not a model-availability issue): ${(await hardError.innerText()).trim()}`);
  }
  await expect(reviewHeading).toBeVisible();

  // Accept as-is: step through the review (persist steps disable Continue while assembling — never click a disabled
  // one; settle until publish appears OR the next Continue re-enables). Mirrors the proven copilot review loop.
  const goLive = page.getByRole("button", { name: /Approve & go live/i });
  const cont = () => page.getByRole("button", { name: /^Continue$/ }).first();
  const atReview = () => goLive.isVisible().catch(() => false);
  for (let guard = 0; guard < 12 && !(await atReview()); guard++) {
    await expect(cont()).toBeEnabled({ timeout: 90_000 });
    await cont().click();
    await expect(async () => {
      const reached = await atReview();
      const nextReady = await cont().isEnabled().catch(() => false);
      expect(reached || nextReady).toBe(true);
    }).toPass({ timeout: 90_000 });
  }
  await expect(goLive).toBeVisible({ timeout: 90_000 });
  const notReady = page.getByText(/Not ready to go live yet/i);
  if (await notReady.isVisible().catch(() => false)) {
    const reason = await notReady.locator("xpath=ancestor::*[self::div][1]").innerText().catch(() => "");
    throw new Error(`copilot produced a draft for ${cfg.seg} but it is NOT publishable:\n${reason.trim()}`);
  }
  await expect(page.getByText(/Ready to go live/i)).toBeVisible();
  await expect(goLive).toBeEnabled();
  await goLive.click();
  await expect
    .poll(async () => (await activePackKeys())?.has(pk) ?? false, { timeout: 60_000, message: `pack ${pk} did not register active after publish` })
    .toBe(true);
  return "published";
}

/** A minimal pega_stub scenario (fireScenario only reads trigger.kind/request + correlation). */
function pegaFlow(scenario: string): Scenario {
  return { domain: "ach_exposure_copilot", pack_keys: [], trigger: { kind: "pega_stub", request: { scenario } },
    correlation: "case_id", hitl: {}, expect: {} };
}

/** Poll the cohort roster → drive each open gate in the Task Inbox as its role-holder; manual-gate values are
 *  SYNTHESIZED from the gate's inferred artifact schema (no hardcoding). Returns the final cohort. */
async function driveToClose(browser: import("@playwright/test").Browser, page: import("@playwright/test").Page,
  correlation: string, wantState = "closed"): Promise<Awaited<ReturnType<typeof cohortByCorrelation>>> {
  const deadline = Date.now() + 300_000;
  const seen = new Set<string>();
  while (Date.now() < deadline) {
    const cohort = await cohortByCorrelation(correlation);
    if (cohort?.state === wantState) return cohort;
    for (const m of cohort?.roster ?? []) {
      const pid = m.process_instance_id;
      if (!pid || (await instanceStatus(pid)) !== "waiting_hitl") continue;
      const task = await openTaskOn(pid);
      if (!task || seen.has(task.task_id)) continue;
      const persona = await personaForRole(POOL, task.role, task.excluded); // role-holding + SoD-correct actor
      if (!persona) continue; // role not materialised yet / SoD-excluded — retry next pass
      seen.add(task.task_id);
      const edits = await synthesizeManualGateEdits(task.task_id, correlation);
      await withPersonaPage(browser, persona as Persona, async (p) => {
        await p.goto(`/inbox/${task.task_id}`);
        await resolveTaskOnPage(p, Object.keys(edits).length ? edits : null);
      });
    }
    await page.waitForTimeout(3000);
  }
  return cohortByCorrelation(correlation);
}

/** MEMBERS=3 joined+terminal+closed with the expected outcome — a 1-member stall fails here. */
async function assertThreeMembersClosed(correlation: string, outcome: string): Promise<void> {
  await expect
    .poll(async () => {
      const c = await cohortByCorrelation(correlation);
      return { members: c?.member_count ?? c?.roster?.length ?? 0, done: c?.rollup?.done ?? 0,
        running: c?.rollup?.running ?? 0, failed: c?.rollup?.failed ?? 0, state: c?.state };
    }, { timeout: 20_000, message: `cohort ${correlation} must reach 3 joined+terminal members and close (a 1-member stall fails here)` })
    .toEqual({ members: 3, done: 3, running: 0, failed: 0, state: "closed" });
  expect(await cohortOutcome(correlation), `cohort outcome should be ${outcome}`).toBe(outcome);
}

test.describe.serial("ACH copilot lifecycle — real-LLM onboard → cohort/DAG/SLA → 3 flows (retains everything)", () => {
  test.use({ persona: "priya" });

  // ── Onboard the 3 segments via the copilot, form the cohort, distribute roles (all read from the live packs) ──
  test("priya copilot-onboards the 3 ACH segments; roles distributed; cohort Members 3 + DAG/SLA", async ({ page }) => {
    test.setTimeout(540_000); // 3 live LLM onboardings + setup

    // Clean-stack guard: this command retains everything, so a re-run must start from a wiped DB.
    if (await cohortDefinitionExists(COHORT_DEF)) {
      ready = { ok: false, reason: `stack not clean — cohort definition '${COHORT_DEF}' already exists; wipe the DB (docker compose … down -v) and re-run` };
      test.skip(true, ready.reason);
      return;
    }

    // 1) Copilot-onboard each segment (real LLM). Skip the whole journey if the model is absent.
    for (const cfg of SEGS) {
      const outcome = await onboardSegment(page, cfg);
      if (outcome === "skip") {
        ready = { ok: false, reason: "copilot LLM not configured on this stack (502 copilot_llm_unavailable)" };
        test.skip(true, ready.reason);
        return;
      }
    }

    // 2) Cohort definition over the CAPTURED pack keys + the enforce→closeout arrival SLA. MUST precede membership:
    //    the registry rejects `cohort-membership` with 422 "unknown cohort definition" until the def exists.
    const st = await createCohortDefinition(COHORT_DEF, [packKey("assess"), packKey("enforce"), packKey("closeout")]);
    expect(st, "create cohort definition").toBeLessThan(300);

    // 3) Cohort membership on each pack (copilot won't) — read-after-write flaky → poll the PUT+GET-verify.
    for (const { seg } of SEGS) {
      await expect
        .poll(() => putCohortMembership(packKey(seg), COHORT_DEF, "case_id"),
          { timeout: 30_000, message: `cohort-membership did not persist on ${packKey(seg)}` })
        .toBe(true);
    }

    // 4) Roles from the packs (data-driven). The copilot frequently infers a 4-eyes `distinct_actor` SoD WITHIN
    //    enforce (e.g. Task_AuthorizeRelease vs Task_PrepareRelease) that a SINGLE enforce approver cannot satisfy —
    //    once marcus authorises the release he is SoD-excluded from the paired action gate, and a lone enforce
    //    holder stalls the segment. With only two process humans available (priya owns + steps out), the robust,
    //    SoD-correct distribution is to grant EVERY gate role to BOTH marcus and riya and drive each gate with the
    //    SoD-aware picker (marcus first; riya when marcus is excluded — see driveToClose → personaForRole). Marcus
    //    is the primary approver; riya provides the second signature the copilot's 4-eyes SoD demands.
    const allRoles = [...new Set([
      ...packGateRoles(await packManifest(packKey("assess"))),
      ...packGateRoles(await packManifest(packKey("enforce"))),
      ...packGateRoles(await packManifest(packKey("closeout"))),
    ])];
    expect(allRoles.length, "the packs declare ≥1 gate role").toBeGreaterThan(0);
    for (const who of ["marcus", "riya"] as const)
      for (const r of allRoles) expect(await grantRole(who, r), `grant ${r} → ${who}`).toBe(true);

    // Structural (stable) assertion: both process humans hold every gate role (so any inferred 4-eyes SoD is
    // satisfiable by two DISTINCT actors), and priya (the owner) drives no gate — poll for role materialisation
    // (amendia_auth ~30s (iss,sub) cache).
    await expect
      .poll(async () => {
        const [m, r, p] = [await personaRoles("marcus"), await personaRoles("riya"), await personaRoles("priya")];
        const bothHold = allRoles.every((x) => m.has(x) && r.has(x));
        const ownerClean = !allRoles.some((x) => p.has(x));
        return bothHold && ownerClean ? "ready" : `bothHold=${bothHold} ownerClean=${ownerClean}`;
      }, { timeout: 60_000, message: "marcus AND riya must hold every gate role (so a 4-eyes SoD is satisfiable); priya (owner) holds none" })
      .toBe("ready");

    // Members 3 — all three packs declare membership in the cohort.
    const members: string[] = [];
    for (const { seg } of SEGS) {
      const cm = (await packManifest(packKey(seg)))?.cohort_membership as { cohort_def_id?: string } | undefined;
      if (cm?.cohort_def_id === COHORT_DEF) members.push(packKey(seg));
    }
    expect(members, "all three copilot packs declare cohort membership").toEqual([packKey("assess"), packKey("enforce"), packKey("closeout")]);

    // DAG + enforce→closeout arrival SLA (owner=external) read back from the definition.
    const def = await cohortDefinition(COHORT_DEF);
    const graph = (def!.expectation_graph ?? def) as { nodes?: { node_id: string }[]; edges?: { from_node: string; to_node: string; sla?: { owner?: string } }[] };
    const nodeIds = (graph.nodes ?? []).map((n) => n.node_id);
    for (const seg of ["assess", "enforce", "closeout"] as const) expect(nodeIds).toContain(packKey(seg));
    const slaEdge = (graph.edges ?? []).find((e) => e.from_node === packKey("enforce") && e.to_node === packKey("closeout") && e.sla);
    expect(slaEdge, "enforce→closeout edge carries an arrival SLA").toBeTruthy();
    expect(slaEdge!.sla!.owner).toBe("external");

    // Owner-gating (folded in): marcus (no platform.admin) does not see the Registry nav.
    await withPersonaPage(page.context().browser()!, "marcus", async (p) => {
      await p.goto("/");
      await p.getByRole("link", { name: "Cohorts" }).first().waitFor({ timeout: 30_000 });
      await expect(p.getByRole("link", { name: "Registry" })).toHaveCount(0);
    });

    ready = { ok: true };
  });

  // ── Flow 1: credit_approve → 3 members, closed / Released ────────────────────────────────────────────────────
  test("credit_approve → 3 members, closed / Released (manual-gate values synthesized from the inferred schema)", async ({ page, browser }) => {
    test.skip(!ready.ok, ready.reason);
    test.setTimeout(360_000);
    let correlation: string;
    try { correlation = await fireScenario(pegaFlow("credit_approve")); } catch (e) { test.skip(true, `pega_stub unavailable: ${e}`); return; }

    await driveToClose(browser, page, correlation);
    await assertThreeMembersClosed(correlation, "Released");

    // Live-SSE (folded in): with the cohort page open and NOT reloaded, the terminal state renders.
    await page.goto(`/cohorts/by-correlation/${correlation}`);
    await expect(page.getByText(/Cohort state\s*closed/i).or(page.locator("text=/^Closed$/")).first()).toBeVisible({ timeout: 25_000 });
    await expect(page.getByText(/Released/).first()).toBeVisible();
  });

  // ── Flow 2: debit_reject → 3 members, closed / Purged ───────────────────────────────────────────────────────
  test("debit_reject → 3 members, closed / Purged", async ({ page, browser }) => {
    test.skip(!ready.ok, ready.reason);
    test.setTimeout(360_000);
    let correlation: string;
    try { correlation = await fireScenario(pegaFlow("debit_reject")); } catch (e) { test.skip(true, `pega_stub unavailable: ${e}`); return; }

    await driveToClose(browser, page, correlation);
    await assertThreeMembersClosed(correlation, "Purged");

    await page.goto(`/cohorts/by-correlation/${correlation}`);
    await expect(page.getByText(/Cohort state\s*closed/i).or(page.locator("text=/^Closed$/")).first()).toBeVisible({ timeout: 25_000 });
    await expect(page.getByText(/Purged/).first()).toBeVisible();
  });

  // ── Flow 3: late_closeout → enforce→closeout arrival SLA breaches (external), case still closes Released ──────
  test("late_closeout → enforce→closeout SLA breaches (external), 3 members, still Released", async ({ page, browser }) => {
    test.skip(!ready.ok, ready.reason);
    test.setTimeout(420_000); // includes the ~25s deliberate closeout delay that breaches the 8s SLA
    let correlation: string;
    try { correlation = await fireScenario(pegaFlow("late_closeout")); } catch (e) { test.skip(true, `pega_stub unavailable: ${e}`); return; }

    await driveToClose(browser, page, correlation);
    await assertThreeMembersClosed(correlation, "Released");

    await expect.poll(async () => (await cohortSla(correlation))?.breaches?.external ?? 0,
      { timeout: 30_000, message: "expected an external-owner SLA breach" }).toBeGreaterThanOrEqual(1);
    const sla = await cohortSla(correlation);
    expect(sla?.states?.some((s) => s.owner === "external" && s.state === "breached"), "a breached, external-owned SLA state").toBe(true);

    await page.goto(`/cohorts/by-correlation/${correlation}`);
    await expect(page.getByText(/SLAs — timing & accountability/i)).toBeVisible({ timeout: 25_000 });
    await expect(page.getByText(/Breaches by owner:/i)).toBeVisible();
    await expect(page.getByText(/external:\s*[1-9]/i)).toBeVisible();
  });
});
