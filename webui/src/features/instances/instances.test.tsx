import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { screen } from "@testing-library/react";
import { renderApp } from "@/test/renderApp";
import { server } from "@/test/server";
import { SERVICE_BASE } from "@/api/config";
import { synthInstanceDetail, synthException, synthPack, TEST_SCHEMA } from "@/test/fixtures";

const R = SERVICE_BASE.runtime;
const REG = SERVICE_BASE.registry;
const ING = SERVICE_BASE.ingestor;
const STUB = SERVICE_BASE.stub;

describe("Instances", () => {
  it("lists instances with statuses", async () => {
    server.use(
      http.get(`${R}/instances`, () =>
        HttpResponse.json([
          synthInstanceDetail().instance,
          { ...synthInstanceDetail().instance, process_instance_id: "PI-TEST-2", status: "running", outcome: null },
        ]),
      ),
    );
    renderApp("/instances", "analyst-1");
    expect(await screen.findByText("PI-TEST-1")).toBeInTheDocument();
    expect(await screen.findByText("PI-TEST-2")).toBeInTheDocument();
  });

  it("shows the actor log and outcome on a completed instance", async () => {
    server.use(
      http.get(`${R}/instances/PI-TEST-1`, () => HttpResponse.json(synthInstanceDetail())),
      http.get(`${R}/instances/PI-TEST-1/state`, () =>
        HttpResponse.json({ process_instance_id: "PI-TEST-1", status: "completed", outcome: "End_Test", artifacts: { thing: { verdict: "ok", note: "synthetic" } }, actor_log: [], trace: {}, last_error: null }),
      ),
      http.get(`${REG}/packs/:key/:version`, () => HttpResponse.json(synthPack)),
      http.get(`${REG}/artifact-schemas/:key/:version`, () => HttpResponse.json({ json_schema: TEST_SCHEMA })),
    );
    renderApp("/instances/PI-TEST-1", "analyst-1");
    expect(await screen.findByText("End_Test")).toBeInTheDocument();
    expect(await screen.findByText(/Actor log/)).toBeInTheDocument();
    expect(await screen.findByText(/Artifacts/)).toBeInTheDocument();
  });
});

describe("Exception detail", () => {
  it("renders the payment parties and journey", async () => {
    server.use(
      http.get(`${STUB}/exceptions/EXC-TEST-001`, () => HttpResponse.json(synthException())),
      http.get(`${ING}/ingestions/EXC-TEST-001`, () =>
        HttpResponse.json({ exception_id: "EXC-TEST-001", status: "accepted", status_history: [{ status: "received", at: "2099-01-01T00:00:00Z", detail: null }], process_instance_id: "PI-TEST-1", resolution: null }),
      ),
    );
    renderApp("/exceptions/EXC-TEST-001", "analyst-1");
    expect(await screen.findByText(/Test Debtor Ltd/)).toBeInTheDocument();
    expect(await screen.findByText(/Test Creditor Ltd/)).toBeInTheDocument();
    expect(await screen.findByText(/Journey/)).toBeInTheDocument();
  });
});

describe("Backend unreachable", () => {
  it("shows the connectivity state instead of an empty table", async () => {
    server.use(http.get(`${R}/instances`, () => HttpResponse.error()));
    renderApp("/instances", "analyst-1");
    expect(await screen.findByText(/is unreachable/i)).toBeInTheDocument();
    expect(await screen.findByText(/docker compose/i)).toBeInTheDocument();
  });
});
