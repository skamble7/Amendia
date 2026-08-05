import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { screen } from "@testing-library/react";
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
  artifacts: { thing: { verdict: "ok", note: "synthetic" } },
  actor_log: [],
  trace: {},
  last_error: null,
};

// pack whose Task_Test output maps art.test.thing → the "thing" artifact, so the decision trail can
// resolve the glea ref to the concrete runtime value.
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

describe("Instance detail — GLEA sections", () => {
  it("composes the glea read-models into the instance view", async () => {
    stubCore();
    server.use(
      http.get(`${GLEA}/audit/instances/:cid/decision-trail`, () => HttpResponse.json(synthDecisionTrail())),
      http.get(`${GLEA}/audit/instances/:cid/lineage`, () => HttpResponse.json(synthLineage())),
      http.get(`${GLEA}/audit/instances/:cid/metrics`, () => HttpResponse.json(synthMetrics())),
      http.get(`${GLEA}/audit/instances/:cid/trace`, () => HttpResponse.json(synthTraceTree())),
      http.get(`${GLEA}/audit/instances/:cid`, () => HttpResponse.json(synthInstanceAudit())),
    );
    renderApp("/instances/PI-TEST-1", "analyst-1");

    // decision trail: gate + Four-eyes badge + comment
    expect(await screen.findByText("Decision trail")).toBeInTheDocument();
    expect(await screen.findByText("Four-eyes")).toBeInTheDocument();
    expect(await screen.findByText(/synthetic approval note/)).toBeInTheDocument();

    // metrics tiles
    expect(await screen.findByText(/Approval latency p50/)).toBeInTheDocument();

    // lineage DAG (custom SVG)
    expect(await screen.findByText("Lineage")).toBeInTheDocument();
    expect(await screen.findByLabelText("artifact lineage graph")).toBeInTheDocument();

    // trace tree + per-instance audit events
    expect(await screen.findByText("Trace")).toBeInTheDocument();
    expect(await screen.findByText("Audit events")).toBeInTheDocument();

    // honest checkpoints line references the real audit rows
    expect(await screen.findByText(/2 audit events recorded/)).toBeInTheDocument();

    // actor-log rationale (from the artifact_committed audit row) — both Task_Test entries carry it
    expect((await screen.findAllByText(/synthetic reasoning for the test artifact/)).length).toBeGreaterThan(0);
  });

  it("renders the core view and degrades gracefully when glea is unreachable", async () => {
    stubCore();
    for (const p of ["", "/decision-trail", "/lineage", "/metrics", "/trace"]) {
      server.use(http.get(`${GLEA}/audit/instances/:cid${p}`, () => HttpResponse.error()));
    }
    renderApp("/instances/PI-TEST-1", "analyst-1");

    // core agent-runtime view still renders
    expect(await screen.findByText("End_Test")).toBeInTheDocument();
    expect(await screen.findByText(/Actor log/)).toBeInTheDocument();

    // every GLEA section degrades to an unavailable note — no crash, no blank page
    expect(await screen.findByText(/Decision trail unavailable/)).toBeInTheDocument();
    expect(await screen.findByText(/Metrics unavailable/)).toBeInTheDocument();
    expect(await screen.findByText(/Lineage unavailable/)).toBeInTheDocument();
    expect(await screen.findByText(/Trace unavailable/)).toBeInTheDocument();
    expect(await screen.findByText(/Audit trail unavailable/)).toBeInTheDocument();

    // checkpoints falls back to the actor-log transition count
    expect(await screen.findByText(/recorded transitions/)).toBeInTheDocument();
  });
});
