// features/registry/waiver.test.tsx — ADR-065 P3: the operator waiver in the UI.
// Covers the shared WaiverAffordance (justification, >= 20 chars, copy) and its wiring into the Bindings step:
// a side-effectful capability reaches 'none' ONLY via a written waiver (D1), the bump drops the waiver on a
// capability change with a notice (D2), and the waiver is sent on save (D1/D5 persist path).
import { describe, it, expect, afterEach, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { server } from "@/test/server";
import { SERVICE_BASE } from "@/api/config";
import { setTestToken } from "@/auth/authToken";
import type { OnboardingSession } from "@/api/services/registry";
import { WaiverAffordance } from "./WaiverAffordance";
import { BindingsStep } from "./OnboardingWizard";

const REG = SERVICE_BASE.registry;
const LONG = "Idempotent status handback to the orchestrator; a re-run is a no-op.";  // >= 20 chars

function wrap(ui: React.ReactNode) {
  setTestToken("test-token");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider delayDuration={0}>
        <MemoryRouter>{ui}</MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("WaiverAffordance", () => {
  it("demands a written justification of >= 20 chars — never a bare toggle — and states the risk plainly", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    wrap(<WaiverAffordance capabilityRef="cap.pay.charge@^1.0.0" waiver={null} onChange={onChange} />);

    // entry is a button, not a checkbox
    expect(screen.queryByRole("checkbox")).toBeNull();
    await user.click(screen.getByRole("button", { name: /waive the human gate/i }));

    // copy names the capability, the real-world action, and the no-approval consequence — unsoftened
    expect(screen.getByText(/real-world action/i)).toBeInTheDocument();
    expect(screen.getByText(/no human approval/i)).toBeInTheDocument();

    const waive = screen.getByRole("button", { name: /^waive the gate$/i });
    expect(waive).toBeDisabled();                                   // empty
    await user.type(screen.getByLabelText(/waiver justification/i), "too short");
    expect(waive).toBeDisabled();                                   // < 20 chars
    await user.clear(screen.getByLabelText(/waiver justification/i));
    await user.type(screen.getByLabelText(/waiver justification/i), LONG);
    expect(waive).toBeEnabled();                                    // >= 20 chars

    await user.click(waive);
    expect(onChange).toHaveBeenCalledWith({ justification: LONG });
  });

  it("shows the justification and can clear the waiver (re-applying the gate)", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    wrap(<WaiverAffordance capabilityRef="cap.pay.charge@^1.0.0" waiver={{ justification: LONG }} onChange={onChange} />);
    expect(screen.getByText(new RegExp(LONG.slice(0, 20)))).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /clear waiver/i }));
    expect(onChange).toHaveBeenCalledWith(null);
  });
});

// -- BindingsStep integration ------------------------------------------------
function bindable(over: Record<string, unknown>) {
  return { element_id: "T", element_kind: "serviceTask", category: "capability", name: "Charge",
           in_event_subprocess: false, is_for_compensation: false, is_multi_instance: false, ...over };
}
function stagedCap(id: string, over: Record<string, unknown> = {}) {
  return { capability_id: id, version: "1.0.0", side_effect: "side_effectful", min_hitl_mode: null,
           input_artifact_key: `art.${id}.in`, input_name: "in", output_artifact_key: `art.${id}.out`,
           output_name: "out", title: id, kind: "mcp", endpoint: "http://mcp/mcp", transport: "streamable_http",
           tool: id.split(".").pop(), ...over };
}
function bindSession(over: Record<string, unknown> = {}): OnboardingSession {
  return {
    session_id: "sess-b", created_by: "o", created_at: "", updated_at: "", state: "capabilities_resolved",
    basics: { pack_key: "p", version: "1.0.0", title: "P", default_domain: "pay" },
    bpmn: { process_id: "P", bpmn_file: "p.bpmn", sha256: "x", required_execution_profile: "common_executable",
            bindable_elements: [bindable({ element_id: "Task_Charge" })], gateways: [], message_flows: [] },
    staged_artifacts: [], staged_capabilities: [stagedCap("cap.pay.charge"), stagedCap("cap.pay.refund")],
    reused_capability_refs: [], triage_rules: [], gateway_variables: [], sod_policies: [], roles: [],
    commit_progress: [], last_cleared: [], conversation: [],
    bindings: [{ element_id: "Task_Charge", element_kind: "serviceTask", executor_type: "capability",
                 capability_ref: "cap.pay.charge@^1.0.0", role: null, hitl_mode: "approve_actions",
                 hitl_role: "role.pay.ops", inputs: [], outputs: [], input_sources: {} }],
    ...over,
  } as unknown as OnboardingSession;
}

function renderBindings(onDone = vi.fn()) {
  server.use(
    http.get(`${REG}/capabilities`, () => HttpResponse.json([])),
    http.get(`${REG}/packs`, () => HttpResponse.json([])),
  );
  return wrap(<BindingsStep session={bindSession()} onDone={onDone} onSession={vi.fn()} nextLabel="Continue" />);
}

describe("BindingsStep — the waiver affordance (ADR-065 P3 D1/D2)", () => {
  afterEach(() => server.resetHandlers());

  it("a side-effectful capability reaches 'none' ONLY via a waiver; setting one drops the gate to none", async () => {
    const user = userEvent.setup();
    renderBindings();

    const modeSelect = await screen.findByRole("combobox", { name: /hitl mode/i }) as HTMLSelectElement;
    const noneOption = Array.from(modeSelect.options).find((o) => o.value === "none")!;
    expect(noneOption.disabled).toBe(true);                         // below the side-effect floor, no waiver yet

    // waive: write a justification → the gate drops to 'none' and the waiver box appears
    await user.click(screen.getByRole("button", { name: /waive the human gate/i }));
    await user.type(screen.getByLabelText(/waiver justification/i), LONG);
    await user.click(screen.getByRole("button", { name: /^waive the gate$/i }));

    expect(await screen.findByTestId("waiver-active")).toBeInTheDocument();
    await waitFor(() => expect((screen.getByRole("combobox", { name: /hitl mode/i }) as HTMLSelectElement).value).toBe("none"));
    // 'none' is now reachable (the waiver lowered the floor)
    const none2 = Array.from((screen.getByRole("combobox", { name: /hitl mode/i }) as HTMLSelectElement).options).find((o) => o.value === "none")!;
    expect(none2.disabled).toBe(false);
  });

  it("changing the capability DROPS the waiver and shows a notice (D2)", async () => {
    const user = userEvent.setup();
    renderBindings();
    // set a waiver first
    await user.click(await screen.findByRole("button", { name: /waive the human gate/i }));
    await user.type(screen.getByLabelText(/waiver justification/i), LONG);
    await user.click(screen.getByRole("button", { name: /^waive the gate$/i }));
    expect(await screen.findByTestId("waiver-active")).toBeInTheDocument();

    // rebind to a DIFFERENT capability → the waiver is dropped + a visible notice explains why
    const capSelect = screen.getByRole("combobox", { name: /capability/i });
    await user.selectOptions(capSelect, "cap.pay.refund@^1.0.0");
    expect(screen.queryByTestId("waiver-active")).toBeNull();
    expect(await screen.findByText(/cleared because the capability changed/i)).toBeInTheDocument();
  });

  it("persists the waiver on save — the PUT /bindings payload carries side_effect_waiver (D1/D5)", async () => {
    const user = userEvent.setup();
    let body: any;
    server.use(http.put(`${REG}/onboarding/sess-b/bindings`, async ({ request }) => {
      body = await request.json();
      return HttpResponse.json(bindSession({ state: "bindings_set" }));
    }));
    renderBindings();

    await user.click(await screen.findByRole("button", { name: /waive the human gate/i }));
    await user.type(screen.getByLabelText(/waiver justification/i), LONG);
    await user.click(screen.getByRole("button", { name: /^waive the gate$/i }));
    await screen.findByTestId("waiver-active");

    await user.click(screen.getByRole("button", { name: /continue/i }));
    await waitFor(() => expect(body).toBeDefined());
    const b = (body.bindings as any[]).find((x) => x.element_id === "Task_Charge");
    expect(b.side_effect_waiver).toEqual({ justification: LONG });
    expect(b.hitl_mode).toBe("none");
  });
});
