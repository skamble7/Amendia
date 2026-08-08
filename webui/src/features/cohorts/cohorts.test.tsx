import { describe, it, expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderApp } from "@/test/renderApp";
import { server } from "@/test/server";
import { SERVICE_BASE } from "@/api/config";
import { synthInstanceDetail, synthPack } from "@/test/fixtures";
import type { BpmnMarker } from "@/features/registry/BpmnViewer";
import type { CohortDetailOut, CohortListOut } from "@/api/types";

// bpmn-js needs real SVG; stub the viewer so we assert wiring (xml fetched + markers passed) not the canvas.
vi.mock("@/features/registry/BpmnViewer", () => ({
  BpmnViewer: ({ xml, markers }: { xml?: string; markers?: BpmnMarker[] }) => (
    <div data-testid="bpmn-viewer">xml:{xml ? "loaded" : "none"} markers:{markers?.length ?? 0}</div>
  ),
}));

const GLEA = SERVICE_BASE.glea;
const REG = SERVICE_BASE.registry;
const R = SERVICE_BASE.runtime;

const LIST: CohortListOut = {
  count: 2,
  cohorts: [
    {
      cohort_instance_id: "coh-1", cohort_def_id: "wire_transfer_cohort", correlation_value: "1v23p",
      state: "closing", member_count: 2, rollup: { done: 1, running: 1, failed: 0 },
      opened_at: "2026-08-08T09:14:02Z", closed_at: null, outcome: null, anomalies: 1,
    },
    {
      cohort_instance_id: "coh-2", cohort_def_id: "wire_transfer_cohort", correlation_value: "9zt4b",
      state: "closed", member_count: 2, rollup: { done: 2, running: 0, failed: 0 },
      opened_at: "2026-08-08T08:41:33Z", closed_at: "2026-08-08T08:47:12Z", outcome: "Resolved", anomalies: 0,
    },
  ],
};

const DETAIL: CohortDetailOut = {
  cohort_instance_id: "coh-1", cohort_def_id: "wire_transfer_cohort", correlation_value: "1v23p",
  state: "closing", member_count: 1, rollup: { done: 0, running: 1, failed: 0 },
  opened_at: "2026-08-08T09:14:02Z", closed_at: null, outcome: "Resolved", anomalies: 1,
  roster: [
    { process_instance_id: "pi-a", pack_key: "wire-repair", pack_version: "1.2.0", correlation_id: "cid-a",
      status: "running", started_at: "2026-08-08T09:16:30Z", ended_at: null, outcome: null, late: false },
    { process_instance_id: "pi-late", pack_key: "wire-return", pack_version: "1.1.0", correlation_id: "cid-late",
      status: "running", started_at: null, ended_at: null, outcome: null, late: true },
  ],
  events: [
    { op: "opened", at: "2026-08-08T09:14:02Z", process_instance_id: null, detail: null },
    { op: "member_joined", at: "2026-08-08T09:16:30Z", process_instance_id: "pi-a", detail: null },
    { op: "closing", at: "2026-08-08T09:19:48Z", process_instance_id: null, detail: "end-of-process from Pega" },
  ],
  close: { signalled: true, outcome: "Resolved", state: "closing", late_joins: 1 },
};

describe("Cohort list", () => {
  it("renders rows with rollup + state chips", async () => {
    server.use(
      http.get(`${GLEA}/cohorts`, () => HttpResponse.json(LIST)),
      http.get(`${REG}/cohort/definitions`, () => HttpResponse.json([{ cohort_def_id: "wire_transfer_cohort", close_schema: {}, close_correlation_path: "exception_id" }])),
    );
    renderApp("/cohorts", "owner-1");
    expect(await screen.findByText("1v23p")).toBeInTheDocument();
    expect(screen.getByText("9zt4b")).toBeInTheDocument();
    expect(screen.getAllByText("Closing").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Closed").length).toBeGreaterThan(0);
    expect(screen.getByText(/1 done · 1 run/)).toBeInTheDocument();
    expect(screen.getByText(/1 late-join/)).toBeInTheDocument();
    expect(screen.getByText("Resolved")).toBeInTheDocument();
  });

  it("shows an empty state when there are no cohorts", async () => {
    server.use(
      http.get(`${GLEA}/cohorts`, () => HttpResponse.json({ count: 0, cohorts: [] })),
      http.get(`${REG}/cohort/definitions`, () => HttpResponse.json([])),
    );
    renderApp("/cohorts", "owner-1");
    expect(await screen.findByText(/No cohorts yet/i)).toBeInTheDocument();
  });
});

describe("Cohort detail — member BPMN diagrams", () => {
  it("renders the roster, one BpmnViewer per member, the event stream and the close card", async () => {
    server.use(
      http.get(`${GLEA}/cohorts/coh-1`, () => HttpResponse.json(DETAIL)),
      http.get(`${REG}/packs/:key/:version`, () => HttpResponse.json(synthPack)),
      http.get(`${REG}/packs/:key/:version/bpmn`, () => HttpResponse.text("<definitions/>")),
      http.get(`${R}/instances/:id`, () => HttpResponse.json(synthInstanceDetail())),
    );
    renderApp("/cohorts/coh-1", "owner-1");

    expect(await screen.findByText("coh-1")).toBeInTheDocument();
    // one member diagram per roster entry (late member included)
    await waitFor(() => expect(screen.getAllByTestId("bpmn-viewer")).toHaveLength(2));
    expect(screen.getAllByTestId("bpmn-viewer")[0]).toHaveTextContent("xml:loaded");

    // late member badge, and member_count (1) differs from roster.length (2)
    expect(screen.getByText(/⚠ late join/)).toBeInTheDocument();
    expect(screen.getByText(/1 Amendia segment/)).toBeInTheDocument();

    // event stream ops + close card
    expect(screen.getByText("opened")).toBeInTheDocument();
    expect(screen.getByText("member_joined")).toBeInTheDocument();
    expect(screen.getByText(/received from orchestrator/i)).toBeInTheDocument();
  });

  it("shows not-found when GLEA has no such cohort", async () => {
    server.use(http.get(`${GLEA}/cohorts/ghost`, () => new HttpResponse(null, { status: 404 })));
    renderApp("/cohorts/ghost", "owner-1");
    expect(await screen.findByText(/Cohort not found/i)).toBeInTheDocument();
  });
});

describe("New cohort", () => {
  it("loads a pack's trigger fields on Add and registers definition + membership on submit", async () => {
    const posted: unknown[] = [];
    const puts: string[] = [];
    server.use(
      http.get(`${REG}/packs`, () => HttpResponse.json([{ ...synthPack, pack_key: "wire-repair", version: "1.2.0" }])),
      http.get(`${REG}/packs/:key/:version/trigger-fields`, () => HttpResponse.json({ fields: ["exception_id", "payment.id"] })),
      http.post(`${REG}/cohort/definitions`, async ({ request }) => {
        posted.push(await request.json());
        return HttpResponse.json({ cohort_def_id: "wire_transfer_cohort", close_schema: {}, close_correlation_path: "exception_id" });
      }),
      http.put(`${REG}/packs/:key/:version/cohort-membership`, ({ params }) => {
        puts.push(`${params.key}@${params.version}`);
        return HttpResponse.json({ ...synthPack });
      }),
      http.get(`${GLEA}/cohorts`, () => HttpResponse.json({ count: 0, cohorts: [] })),
      http.get(`${REG}/cohort/definitions`, () => HttpResponse.json([])),
    );
    const user = userEvent.setup();
    renderApp("/cohorts/new", "owner-1");

    await user.clear(await screen.findByLabelText(/Cohort id/i));
    await user.type(screen.getByLabelText(/Cohort id/i), "wire_transfer_cohort");

    // Add the pack → its trigger fields populate the correlation-key selector.
    await user.click(await screen.findByRole("button", { name: /Add/i }));
    const select = await screen.findByRole("combobox");
    expect(within(select).getByRole("option", { name: "exception_id" })).toBeInTheDocument();
    expect(within(select).getByRole("option", { name: "payment.id" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Register cohort/i }));

    expect(posted).toHaveLength(1);
    expect((posted[0] as { cohort_def_id: string }).cohort_def_id).toBe("wire_transfer_cohort");
    expect(puts).toEqual(["wire-repair@1.2.0"]);
  });

  it("blocks submit when the close schema is not valid JSON", async () => {
    const posted: unknown[] = [];
    server.use(
      http.get(`${REG}/packs`, () => HttpResponse.json([])),
      http.post(`${REG}/cohort/definitions`, async ({ request }) => { posted.push(await request.json()); return HttpResponse.json({}); }),
    );
    const user = userEvent.setup();
    renderApp("/cohorts/new", "owner-1");

    await user.type(await screen.findByLabelText(/Cohort id/i), "c1");
    const schema = screen.getByLabelText(/Close message schema/i);
    await user.clear(schema);
    await user.type(schema, "{{ not json");   // "{{" types a literal "{" in userEvent
    await user.click(screen.getByRole("button", { name: /Register cohort/i }));

    expect(await screen.findByText(/not valid JSON/i)).toBeInTheDocument();
    expect(posted).toHaveLength(0); // never hit the API
  });
});

describe("Instance cohort backlink", () => {
  it("shows the backlink banner when the instance joined a cohort", async () => {
    server.use(
      http.get(`${R}/instances/PI-TEST-1`, () =>
        HttpResponse.json(synthInstanceDetail({
          cohort_instance_id: "coh-1", cohort_def_id: "wire_transfer_cohort", cohort_correlation_value: "1v23p",
        })),
      ),
      http.get(`${R}/instances/PI-TEST-1/state`, () => new HttpResponse(null, { status: 404 })),
      http.get(`${REG}/packs/:key/:version`, () => HttpResponse.json(synthPack)),
      http.get(`${GLEA}/cohorts/coh-1`, () => HttpResponse.json(DETAIL)),
    );
    renderApp("/instances/PI-TEST-1", "analyst-1");
    expect(await screen.findByText(/Part of cohort/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /View cohort/i })).toHaveAttribute("href", "/cohorts/coh-1");
  });

  it("does not show the banner for a standalone instance", async () => {
    server.use(
      http.get(`${R}/instances/PI-TEST-1`, () => HttpResponse.json(synthInstanceDetail())), // no cohort fields
      http.get(`${R}/instances/PI-TEST-1/state`, () => new HttpResponse(null, { status: 404 })),
      http.get(`${REG}/packs/:key/:version`, () => HttpResponse.json(synthPack)),
    );
    renderApp("/instances/PI-TEST-1", "analyst-1");
    expect(await screen.findByText("End_Test")).toBeInTheDocument(); // page rendered
    expect(screen.queryByText(/Part of cohort/i)).not.toBeInTheDocument();
  });
});
