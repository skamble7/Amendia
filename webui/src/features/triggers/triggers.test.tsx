import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderApp } from "@/test/renderApp";
import { server } from "@/test/server";
import { SERVICE_BASE } from "@/api/config";

const STUB = SERVICE_BASE.stub;
const ING = SERVICE_BASE.ingestor;

// one row so the empty-state (which renders a SECOND generate button) stays hidden — a single control.
const ONE_INGESTION = [{
  trigger_id: "exc-1", trigger_type: "unable_to_apply", status: "received",
  resolution: null, process_instance_id: null, updated_at: new Date().toISOString(),
}];

const CATALOG = {
  generators: [
    { id: "wire", label: "Wire exception", endpoint: "/generators/wire/generate",
      scenarios: [{ id: "AC01", label: "AC01 · account closed", body: { reason_code: "AC01" } }] },
    { id: "dine_in", label: "Restaurant dine-in", endpoint: "/generators/dine_in/generate",
      scenarios: [
        { id: "happy", label: "Happy path", body: {} },
        { id: "tender_declined", label: "Declined tender · payment-resolve loop", body: { tender_declined: true } },
      ] },
  ],
};

describe("Triggers page — domain-neutral trigger panel (ADR-052)", () => {
  it("drives the trigger from the stub's generator catalog, not hardcoded reason codes", async () => {
    let posted: { path: string; body: unknown } | null = null;
    server.use(
      http.get(`${ING}/ingestions`, () => HttpResponse.json(ONE_INGESTION)),
      http.get(`${STUB}/generators`, () => HttpResponse.json(CATALOG)),
      http.post(`${STUB}/generators/dine_in/generate`, async ({ request }) => {
        posted = { path: "/generators/dine_in/generate", body: await request.json() };
        return HttpResponse.json({ created: [{ trigger: { trigger_id: "TKT-9" } }] }, { status: 201 });
      }),
    );
    renderApp("/triggers", "owner-1");

    // domain-neutral header copy
    expect(await screen.findByText("Incoming triggers and their ingestion lifecycle.")).toBeInTheDocument();

    // Source select is catalog-driven — both generators, no reason-code literals
    expect(await screen.findByRole("option", { name: "Wire exception" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Restaurant dine-in" })).toBeInTheDocument();

    // pick the dine-in source → its scenarios appear
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Trigger source" }), "dine_in");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Scenario" }), "tender_declined");

    await userEvent.click(screen.getByRole("button", { name: /Generate trigger \(via stub source\)/ }));

    // POSTed the chosen scenario body to the dine-in generator's own endpoint
    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted!.path).toBe("/generators/dine_in/generate");
    expect(posted!.body).toEqual({ tender_declined: true });
  });

  it("disables the control with a 'stub unreachable' tooltip when the catalog fails to load", async () => {
    server.use(
      http.get(`${ING}/ingestions`, () => HttpResponse.json(ONE_INGESTION)),
      http.get(`${STUB}/generators`, () => HttpResponse.json({ detail: "down" }, { status: 503 })),
    );
    renderApp("/triggers", "owner-1");

    await waitFor(() => {
      const btn = screen.getByRole("button", { name: /Generate trigger \(via stub source\)/ });
      expect(btn).toBeDisabled();
      expect(btn).toHaveAttribute("title", expect.stringContaining("stub unreachable"));
    });
  });
});
