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

// --------------------------------------------------------------------------- #
// ADR-063 definitions surface (instances vs definitions split)
// --------------------------------------------------------------------------- #
const DEFS = [{
  cohort_def_id: "ach_exposure_cohort", display_name: "ACH exposure",
  close_schema: { type: "object", properties: { event: { const: "process_completed" }, case_id: { type: "string" } } },
  close_correlation_path: "case_id", close_outcome_path: "outcome",
}];
const member = (key: string) => ({ ...synthPack, pack_key: key, version: "1.0.0",
  cohort_membership: { cohort_def_id: "ach_exposure_cohort", correlation_key: "case_id" } });
const ACTIVE_PACKS = [member("ach-assess"), member("ach-enforce"), member("ach-closeout"),
  { ...synthPack, pack_key: "wire-repair", version: "1.2.0" }]; // unassigned candidate
const ACH_LIST: CohortListOut = { count: 1, cohorts: [{
  cohort_instance_id: "coh-ach1", cohort_def_id: "ach_exposure_cohort", correlation_value: "CASE-1",
  state: "closing", member_count: 3, rollup: { done: 1, running: 2, failed: 0 },
  opened_at: "2026-08-09T09:00:00Z", closed_at: null, outcome: null, anomalies: 0 }] };

describe("Cohort definitions surface", () => {
  it("defaults to Instances and flips to Definitions (URL-persisted)", async () => {
    server.use(
      http.get(`${GLEA}/cohorts`, () => HttpResponse.json(ACH_LIST)),
      http.get(`${REG}/cohort/definitions`, () => HttpResponse.json(DEFS)),
      http.get(`${REG}/packs`, () => HttpResponse.json(ACTIVE_PACKS)),
    );
    const user = userEvent.setup();
    renderApp("/cohorts", "owner-1");
    // Instances tab is default → instance rows show
    expect(await screen.findByText("CASE-1")).toBeInTheDocument();
    // flip to Definitions
    await user.click(screen.getByRole("tab", { name: /definitions/i }));
    expect(await screen.findByText("ach_exposure_cohort")).toBeInTheDocument();
    expect(screen.getByText(/event=process_completed → case_id/)).toBeInTheDocument();
  });

  it("opens directly on Definitions via ?tab and shows Members=3, Instances=1", async () => {
    server.use(
      http.get(`${GLEA}/cohorts`, () => HttpResponse.json(ACH_LIST)),
      http.get(`${REG}/cohort/definitions`, () => HttpResponse.json(DEFS)),
      http.get(`${REG}/packs`, () => HttpResponse.json(ACTIVE_PACKS)),
    );
    renderApp("/cohorts?tab=definitions", "owner-1");
    const cell = await screen.findByText("ach_exposure_cohort");
    const row = cell.closest("tr")!;
    expect(within(row).getByText("3")).toBeInTheDocument();  // members
    expect(within(row).getByText("1")).toBeInTheDocument();  // instances
  });
});

describe("Cohort definition detail", () => {
  it("renders members, close schema, forward-only warning, and instances panel", async () => {
    server.use(
      http.get(`${GLEA}/cohorts`, () => HttpResponse.json(ACH_LIST)),
      http.get(`${REG}/cohort/definitions`, () => HttpResponse.json(DEFS)),
      http.get(`${REG}/packs`, () => HttpResponse.json(ACTIVE_PACKS)),
      http.get(`${REG}/packs/:key/:version/trigger-fields`, () => HttpResponse.json({ fields: ["case_id", "exception_id"] })),
    );
    renderApp("/cohorts/definitions/ach_exposure_cohort", "owner-1");
    expect(await screen.findByText("ach-assess")).toBeInTheDocument();
    expect(screen.getByText("ach-enforce")).toBeInTheDocument();
    expect(screen.getByText("ach-closeout")).toBeInTheDocument();
    // close schema pretty-printed + forward-only warning (1 instance) + instances panel row
    expect(screen.getByText(/"process_completed"/)).toBeInTheDocument();
    expect(screen.getByText(/forward-only/i)).toBeInTheDocument();
    expect(screen.getByText("CASE-1")).toBeInTheDocument();
  });

  it("Remove then Add round-trips against the registry and the member list updates", async () => {
    let packs = ACTIVE_PACKS.map((p) => ({ ...p }));
    const calls: string[] = [];
    server.use(
      http.get(`${GLEA}/cohorts`, () => HttpResponse.json(ACH_LIST)),
      http.get(`${REG}/cohort/definitions`, () => HttpResponse.json(DEFS)),
      http.get(`${REG}/packs`, () => HttpResponse.json(packs)),
      http.get(`${REG}/packs/:key/:version/trigger-fields`, () => HttpResponse.json({ fields: ["case_id", "exception_id"] })),
      http.delete(`${REG}/packs/:key/:version/cohort-membership`, ({ params }) => {
        calls.push(`DELETE ${params.key}`);
        packs = packs.map((p) => (p.pack_key === params.key ? { ...p, cohort_membership: undefined } : p));
        return HttpResponse.json({});
      }),
      http.put(`${REG}/packs/:key/:version/cohort-membership`, async ({ params, request }) => {
        const body = (await request.json()) as { correlation_key: string };
        calls.push(`PUT ${params.key}=${body.correlation_key}`);
        packs = packs.map((p) => (p.pack_key === params.key
          ? { ...p, cohort_membership: { cohort_def_id: "ach_exposure_cohort", correlation_key: body.correlation_key } } : p));
        return HttpResponse.json({});
      }),
    );
    const user = userEvent.setup();
    renderApp("/cohorts/definitions/ach_exposure_cohort", "owner-1");

    // Remove ach-assess → row disappears after refetch
    const assessRow = (await screen.findByText("ach-assess")).closest("tr")!;
    await user.click(within(assessRow).getByRole("button", { name: /Remove/i }));
    await waitFor(() => expect(screen.queryByText("ach-assess")).not.toBeInTheDocument());
    expect(calls).toContain("DELETE ach-assess");

    // Add it back via the + Add pack control (now an unassigned candidate), key case_id
    await user.selectOptions(screen.getByRole("combobox", { name: /Add pack/i }), "ach-assess@1.0.0");
    await user.selectOptions(screen.getByRole("combobox", { name: /New member correlation key/i }), "case_id");
    await user.click(screen.getByRole("button", { name: /^Add$/i }));
    await waitFor(() => expect(screen.getByText("ach-assess")).toBeInTheDocument());
    expect(calls).toContain("PUT ach-assess=case_id");
  });
});

describe("Cohort definition inline edit", () => {
  it("owner edits display_name + close_schema in place, Save PUTs and the card updates", async () => {
    let defs: Array<Record<string, unknown>> = DEFS.map((d) => ({ ...d }));
    const puts: Array<Record<string, unknown>> = [];
    server.use(
      http.get(`${GLEA}/cohorts`, () => HttpResponse.json(ACH_LIST)),
      http.get(`${REG}/cohort/definitions`, () => HttpResponse.json(defs)),
      http.get(`${REG}/packs`, () => HttpResponse.json(ACTIVE_PACKS)),
      http.get(`${REG}/packs/:key/:version/trigger-fields`, () => HttpResponse.json({ fields: ["case_id"] })),
      http.put(`${REG}/cohort/definitions/:id`, async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        puts.push(body);
        defs = [{ ...defs[0], ...body }]; // reflect the update on the next GET
        return HttpResponse.json({ cohort_def_id: "ach_exposure_cohort", ...body, created_at: "x", updated_at: "y" });
      }),
    );
    const user = userEvent.setup();
    renderApp("/cohorts/definitions/ach_exposure_cohort", "owner-1");

    // read-only header shows the current display name
    expect(await screen.findByText("ACH exposure")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Edit definition/i }));

    const name = screen.getByLabelText(/Display name/i);
    await user.clear(name);
    await user.type(name, "ACH renamed");
    const schema = screen.getByLabelText(/Close message schema/i);
    await user.clear(schema);
    await user.type(schema, '{{"type":"object"}'); // "{{" → literal "{" → valid JSON

    await user.click(screen.getByRole("button", { name: /^Save$/i }));

    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]?.display_name).toBe("ACH renamed");
    expect(puts[0]?.close_schema).toEqual({ type: "object" });
    // card refreshed (list invalidated) → new display name, back to read-only (Edit button returns)
    expect(await screen.findByText("ACH renamed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Edit definition/i })).toBeInTheDocument();
  });

  it("blocks Save on invalid JSON and Cancel restores without a request", async () => {
    const puts: unknown[] = [];
    server.use(
      http.get(`${GLEA}/cohorts`, () => HttpResponse.json(ACH_LIST)),
      http.get(`${REG}/cohort/definitions`, () => HttpResponse.json(DEFS)),
      http.get(`${REG}/packs`, () => HttpResponse.json(ACTIVE_PACKS)),
      http.get(`${REG}/packs/:key/:version/trigger-fields`, () => HttpResponse.json({ fields: ["case_id"] })),
      http.put(`${REG}/cohort/definitions/:id`, async ({ request }) => { puts.push(await request.json()); return HttpResponse.json({}); }),
    );
    const user = userEvent.setup();
    renderApp("/cohorts/definitions/ach_exposure_cohort", "owner-1");

    await user.click(await screen.findByRole("button", { name: /Edit definition/i }));
    const schema = screen.getByLabelText(/Close message schema/i);
    await user.clear(schema);
    await user.type(schema, "{{ not json");
    await user.click(screen.getByRole("button", { name: /^Save$/i }));
    expect(await screen.findByText(/not valid JSON/i)).toBeInTheDocument();
    expect(puts).toHaveLength(0);

    // Cancel exits edit mode with no request; read-only view returns
    await user.click(screen.getByRole("button", { name: /Cancel/i }));
    expect(screen.getByRole("button", { name: /Edit definition/i })).toBeInTheDocument();
    expect(screen.queryByLabelText(/Close message schema/i)).not.toBeInTheDocument();
    expect(puts).toHaveLength(0);
  });

  it("a non-owner sees no Edit control", async () => {
    server.use(
      http.get(`${GLEA}/cohorts`, () => HttpResponse.json(ACH_LIST)),
      http.get(`${REG}/cohort/definitions`, () => HttpResponse.json(DEFS)),
      http.get(`${REG}/packs`, () => HttpResponse.json(ACTIVE_PACKS)),
      http.get(`${REG}/packs/:key/:version/trigger-fields`, () => HttpResponse.json({ fields: ["case_id"] })),
    );
    renderApp("/cohorts/definitions/ach_exposure_cohort", "analyst-1");
    expect(await screen.findByText("ach_exposure_cohort")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Edit definition/i })).not.toBeInTheDocument();
  });
});

describe("Instance detail — definition backlink (no membership mgmt)", () => {
  it("shows a read-only Definition link and no Manage-membership button", async () => {
    server.use(http.get(`${GLEA}/cohorts/coh-1`, () => HttpResponse.json(DETAIL)),
      http.get(`${REG}/packs/:key/:version`, () => HttpResponse.json(synthPack)),
      http.get(`${REG}/packs/:key/:version/bpmn`, () => HttpResponse.text("<definitions/>")),
      http.get(`${R}/instances/:id`, () => HttpResponse.json(synthInstanceDetail())));
    renderApp("/cohorts/coh-1", "owner-1");
    const link = await screen.findByRole("link", { name: /Definition:/i });
    expect(link).toHaveAttribute("href", "/cohorts/definitions/wire_transfer_cohort");
    expect(screen.queryByRole("button", { name: /Manage membership/i })).not.toBeInTheDocument();
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
