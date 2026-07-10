import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { screen } from "@testing-library/react";
import { renderApp } from "@/test/renderApp";
import { server } from "@/test/server";
import { SERVICE_BASE } from "@/api/config";

const STUB = SERVICE_BASE.stub;
const ING = SERVICE_BASE.ingestor;
const R = SERVICE_BASE.runtime;

const now = () => new Date().toISOString();
const ago = (mins: number) => new Date(Date.now() - mins * 60_000).toISOString();

/** Stub all six dashboard endpoints; `status`-filtered variants branch on the query. */
function stubDashboard(opts: {
  exceptions?: unknown[];
  ingestions?: unknown[];
  noProcess?: unknown[];
  instances?: unknown[];
  failed?: unknown[];
  openTasks?: unknown[];
} = {}) {
  server.use(
    http.get(`${STUB}/exceptions`, () => HttpResponse.json(opts.exceptions ?? [])),
    http.get(`${ING}/ingestions`, ({ request }) => {
      const status = new URL(request.url).searchParams.get("status");
      if (status === "no_process") return HttpResponse.json(opts.noProcess ?? []);
      return HttpResponse.json(opts.ingestions ?? []);
    }),
    http.get(`${R}/instances`, ({ request }) => {
      const status = new URL(request.url).searchParams.get("status");
      if (status === "failed") return HttpResponse.json(opts.failed ?? []);
      return HttpResponse.json(opts.instances ?? []);
    }),
    http.get(`${R}/hitl-tasks`, () => HttpResponse.json(opts.openTasks ?? [])),
  );
}

describe("Dashboard — Today's pipeline", () => {
  it("renders the stage counters from stubbed lists", async () => {
    stubDashboard({
      exceptions: [
        { exception_id: "E1", reason_codes: ["AC01"], created_at: now() },
        { exception_id: "E2", reason_codes: ["AC01"], created_at: now() },
        { exception_id: "E3", reason_codes: ["AC04"], created_at: now() },
      ],
      ingestions: [
        { exception_id: "E1", status: "received", created_at: now() },
        { exception_id: "E2", status: "dispatched", created_at: now() },
        { exception_id: "E3", status: "dispatched", created_at: now() },
        { exception_id: "E4", status: "accepted", created_at: now() },
        { exception_id: "E5", status: "no_process", created_at: now() },
      ],
      instances: [
        { process_instance_id: "P1", status: "running", created_at: now() },
        { process_instance_id: "P2", status: "running", created_at: now() },
        { process_instance_id: "P3", status: "waiting_hitl", created_at: now() },
        { process_instance_id: "P4", status: "completed", created_at: now() },
        { process_instance_id: "P5", status: "completed", created_at: now() },
        { process_instance_id: "P6", status: "completed", created_at: now() },
        { process_instance_id: "P7", status: "completed", created_at: now() },
      ],
    });
    renderApp("/dashboard", "analyst-1");

    // The accessible name is label + value once loaded (skeleton has no text),
    // so matching the value waits past the loading state.
    expect(await screen.findByRole("link", { name: /Raised 3/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ingested 5/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^Dispatched 3/ })).toBeInTheDocument(); // 2 dispatched + 1 accepted
    expect(screen.getByRole("link", { name: /Completed 4/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /No process 1/ })).toBeInTheDocument();
  });
});

describe("Dashboard — Waiting on human", () => {
  it("shows the queue depth with avg and oldest wait", async () => {
    stubDashboard({
      openTasks: [{ task_id: "t1", created_at: ago(10) }, { task_id: "t2", created_at: ago(30) }],
    });
    renderApp("/dashboard", "analyst-1");
    expect(await screen.findByText("Waiting on human")).toBeInTheDocument();
    expect(await screen.findByText(/Avg wait/)).toHaveTextContent("20m");
    expect(screen.getByText(/Oldest task/)).toHaveTextContent("30m");
    expect(screen.getByRole("link", { name: /Open task inbox/ })).toHaveAttribute("href", "/inbox");
  });
});

describe("Dashboard — Needs triage", () => {
  it("lists failed instances and no-process ingestions", async () => {
    stubDashboard({
      failed: [{ process_instance_id: "PI-BUST", status: "failed", last_error: "sanctions HIT" }],
      noProcess: [{ exception_id: "EXC-ORPHAN", status: "no_process", created_at: now() }],
    });
    renderApp("/dashboard", "analyst-1");
    expect(await screen.findByText("PI-BUST")).toBeInTheDocument();
    expect(screen.getByText("sanctions HIT")).toBeInTheDocument();
    expect(screen.getByText("EXC-ORPHAN")).toBeInTheDocument();
    expect(screen.getByText("No matching process")).toBeInTheDocument();
  });

  it("shows the empty state when nothing needs triage", async () => {
    stubDashboard({});
    renderApp("/dashboard", "analyst-1");
    expect(await screen.findByText("Nothing to triage")).toBeInTheDocument();
  });
});

describe("Dashboard — By reason code", () => {
  it("tallies reason codes into bars", async () => {
    stubDashboard({
      exceptions: [
        { exception_id: "E1", reason_codes: ["AC01", "AC04"], created_at: now() },
        { exception_id: "E2", reason_codes: ["AC01"], created_at: now() },
      ],
    });
    renderApp("/dashboard", "analyst-1");
    expect(await screen.findByText("AC01")).toBeInTheDocument();
    expect(screen.getByText("AC04")).toBeInTheDocument();
  });
});

describe("Dashboard — connectivity", () => {
  it("surfaces the unreachable banner when a service is down", async () => {
    server.use(
      http.get(`${STUB}/exceptions`, () => HttpResponse.error()),
      http.get(`${ING}/ingestions`, () => HttpResponse.json([])),
      http.get(`${R}/instances`, () => HttpResponse.json([])),
      http.get(`${R}/hitl-tasks`, () => HttpResponse.json([])),
    );
    renderApp("/dashboard", "analyst-1");
    expect(await screen.findByText(/is unreachable/i)).toBeInTheDocument();
  });
});
