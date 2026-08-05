import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderApp } from "@/test/renderApp";
import { server } from "@/test/server";
import { SERVICE_BASE } from "@/api/config";
import {
  synthInstanceDetail,
  synthPack,
  TEST_SCHEMA,
  synthDecisionTrail,
  synthLineage,
  synthMetrics,
  synthTraceTree,
  synthInstanceAudit,
} from "@/test/fixtures";

const R = SERVICE_BASE.runtime;
const REG = SERVICE_BASE.registry;
const GLEA = SERVICE_BASE.glea;

const stateWithThing = {
  process_instance_id: "PI-TEST-1",
  status: "completed",
  outcome: "End_Test",
  artifacts: { thing: { verdict: "ok", note: "synthetic-value" } },
  actor_log: [],
  trace: {},
  last_error: null,
};

// pack whose Task_Test output maps art.test.thing → the "thing" artifact.
const packWithOutput = {
  ...synthPack,
  bindings: [{ ...synthPack.bindings[0], outputs: [{ name: "thing", schema: "art.test.thing@1.0.0" }] }],
};

function stubCore() {
  server.use(
    http.get(`${R}/instances/PI-TEST-1`, () => HttpResponse.json(synthInstanceDetail())),
    http.get(`${R}/instances/PI-TEST-1/state`, () => HttpResponse.json(stateWithThing)),
    http.get(`${REG}/packs/:key/:version`, () => HttpResponse.json(packWithOutput)),
    http.get(`${REG}/artifact-schemas/:key/:version`, () => HttpResponse.json({ json_schema: TEST_SCHEMA })),
  );
}

const user = userEvent.setup();
const tab = async (name: RegExp) => user.click(await screen.findByRole("tab", { name }));

describe("Instance detail — tabbed GLEA layout", () => {
  it("composes the glea read-models across header, KPI strip and tabs", async () => {
    stubCore();
    server.use(
      http.get(`${GLEA}/audit/instances/:cid/decision-trail`, () => HttpResponse.json(synthDecisionTrail())),
      http.get(`${GLEA}/audit/instances/:cid/lineage`, () => HttpResponse.json(synthLineage())),
      http.get(`${GLEA}/audit/instances/:cid/metrics`, () => HttpResponse.json(synthMetrics())),
      http.get(`${GLEA}/audit/instances/:cid/trace`, () => HttpResponse.json(synthTraceTree())),
      http.get(`${GLEA}/audit/instances/:cid`, () => HttpResponse.json(synthInstanceAudit())),
    );
    renderApp("/instances/PI-TEST-1", "analyst-1");

    // header + KPI strip (always visible)
    expect(await screen.findByText("End_Test")).toBeInTheDocument();
    expect(await screen.findByText(/Approval latency/)).toBeInTheDocument();
    expect(await screen.findByText("Duration")).toBeInTheDocument();

    // Overview (default): activity feed rationale + honest checkpoints line
    expect((await screen.findAllByText(/synthetic reasoning for the test artifact/)).length).toBeGreaterThan(0);
    expect(await screen.findByText(/2 audit events recorded/)).toBeInTheDocument();

    // Governance tab: decision trail (comment) + audit events
    await tab(/Governance/);
    expect(await screen.findByText("Decision trail")).toBeInTheDocument();
    expect(await screen.findByText(/synthetic approval note/)).toBeInTheDocument();
    expect(await screen.findByText("Audit events")).toBeInTheDocument();

    // Observability tab: lineage DAG + trace
    await tab(/Observability/);
    expect(await screen.findByLabelText("artifact lineage graph")).toBeInTheDocument();
    expect(await screen.findByText("Trace")).toBeInTheDocument();
  });

  it("renders the core view and degrades gracefully per tab when glea is unreachable", async () => {
    stubCore();
    for (const p of ["", "/decision-trail", "/lineage", "/metrics", "/trace"]) {
      server.use(http.get(`${GLEA}/audit/instances/:cid${p}`, () => HttpResponse.error()));
    }
    renderApp("/instances/PI-TEST-1", "analyst-1");

    // core view: header outcome + activity feed always render
    expect(await screen.findByText("End_Test")).toBeInTheDocument();
    expect(await screen.findByText("Activity")).toBeInTheDocument();
    // KPI strip: Duration always renders; the five glea tiles degrade to "unavailable"
    expect(await screen.findByText("Duration")).toBeInTheDocument();
    expect((await screen.findAllByText(/unavailable/)).length).toBeGreaterThan(0);
    // checkpoints falls back to the actor-log transition count (Overview tab)
    expect(await screen.findByText(/recorded transitions/)).toBeInTheDocument();

    // Governance tab: both GLEA sections show an unavailable note
    await tab(/Governance/);
    expect(await screen.findByText(/Decision trail unavailable/)).toBeInTheDocument();
    expect(await screen.findByText(/Audit trail unavailable/)).toBeInTheDocument();

    // Observability tab: lineage + trace unavailable
    await tab(/Observability/);
    expect(await screen.findByText(/Lineage unavailable/)).toBeInTheDocument();
    expect(await screen.findByText(/Trace unavailable/)).toBeInTheDocument();
  });

  it("shows artifacts as an accordion collapsed by default; expanding reveals the value", async () => {
    stubCore(); // glea uses the default empty handlers from server.ts
    renderApp("/instances/PI-TEST-1", "analyst-1");

    await tab(/Artifacts/);
    // the row header (artifact name) is visible; the value is NOT (collapsed by default)
    const toggle = await screen.findByRole("button", { name: /thing/ });
    expect(toggle).toBeInTheDocument();
    expect(screen.queryByText(/synthetic-value/)).not.toBeInTheDocument();

    // expand the row → the ArtifactView value renders
    await user.click(toggle);
    expect(await screen.findByText(/synthetic-value/)).toBeInTheDocument();

    // Expand all / Collapse all toggle exists and collapses again
    await user.click(await screen.findByRole("button", { name: /Collapse all|Expand all/ }));
  });
});
