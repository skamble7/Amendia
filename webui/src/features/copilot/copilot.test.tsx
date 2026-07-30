// features/copilot/copilot.test.tsx — the business-facing copilot flow (ADR-052 2c). Mocks the API; asserts the
// plain-language Review, the go-live gating, conversational refine, generic humanization, and navigation.
import { describe, it, expect, afterEach, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { render, screen, waitFor, within, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { server } from "@/test/server";
import { SERVICE_BASE } from "@/api/config";
import { setTestToken } from "@/auth/authToken";
import { CopilotFlow } from "./CopilotFlow";

// bpmn-js needs real SVG layout (getBBox) that jsdom lacks; the diagram itself isn't under test here.
vi.mock("@/features/registry/BpmnViewer", () => ({ BpmnViewer: () => <div data-testid="bpmn-viewer" /> }));

const REG = SERVICE_BASE.registry;

function renderCopilot(path: string) {
  setTestToken("test-token");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider delayDuration={0}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/registry/onboard" element={<CopilotFlow />} />
            <Route path="/registry/onboard/:sessionId" element={<CopilotFlow />} />
            <Route path="/registry/onboard/technical/:sessionId" element={<div>TECHNICAL INSPECTION WIZARD</div>} />
          </Routes>
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

function binding(over: Record<string, unknown>) {
  return {
    element_id: "X", element_kind: "serviceTask", executor_type: "capability", capability_ref: null,
    role: null, hitl_mode: "none", hitl_role: null, inputs: [], outputs: [], input_sources: {}, ...over,
  };
}

function session(over: Record<string, unknown> = {}) {
  return {
    session_id: "sess-c", created_by: "owner-1", created_at: "", updated_at: "", state: "assembled",
    basics: { pack_key: "rest-stan", version: "1.0.0", title: "Restaurant dine-in", default_domain: "rest_stan" },
    staged_artifacts: [], staged_capabilities: [], reused_capability_refs: [], triage_rules: [],
    gateway_variables: [], sod_policies: [], roles: [], commit_progress: [], last_cleared: [], conversation: [],
    bindings: [
      binding({ element_id: "Task_PresentMenu", capability_ref: "cap.rest_stan.get_menu@^1.0.0", hitl_mode: "none" }),
      binding({ element_id: "Task_SelectItems", executor_type: "human", role: "role.rest_stan.diner",
                hitl_mode: "manual", hitl_role: "role.rest_stan.diner" }),
      binding({ element_id: "Task_FireTicket", capability_ref: "cap.rest_stan.fire_ticket@^1.0.0",
                hitl_mode: "approve_actions", hitl_role: "role.rest_stan.kitchen" }),
    ],
    dry_run_report: { pack_key: "rest-stan", pack_version: "1.0.0", findings: [], created_at: "" },
    copilot_report: {
      summary: "When a party is seated the menu is shown; the diner selects items; the kitchen checks availability.",
      decisions: [], llm_used: true, model_ref: null, repair_passes: 0,
      open_questions: [{ topic: "triage", element_id: null, confidence: 0.4,
                         question: "Should dine-in tickets route to this process?" }],
    },
    ...over,
  };
}

describe("Copilot flow — Start", () => {
  afterEach(() => server.resetHandlers());

  // Fill everything Generate requires: BPMN, MCP, the trigger (a sample event) and one triage rule.
  async function fillAll(user: ReturnType<typeof userEvent.setup>) {
    await user.upload(screen.getByLabelText("BPMN file"),
      new File(["<bpmn:definitions/>"], "my-process.bpmn", { type: "application/xml" }));
    await user.type(screen.getByLabelText(/tools \(MCP/i), "http://mcp.local/mcp");
    // paste the trigger via fireEvent (userEvent.type would interpret JSON braces as key sequences)
    fireEvent.change(screen.getByLabelText(/trigger event or schema/i),
      { target: { value: JSON.stringify({ order_type: "dine_in", dietary_flags: ["nuts"] }) } });
    await user.click(await screen.findByRole("button", { name: /add rule/i }));
    await user.type(screen.getByLabelText("Value"), "dine_in");   // field defaults to order_type, op to eq
  }

  it("Generate is gated on a valid trigger + at least one triage rule, then sends the right body", async () => {
    const user = userEvent.setup();
    let body: Record<string, unknown> | undefined;
    server.use(
      http.post(`${REG}/onboarding/copilot/generate`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(session(), { status: 201 });
      }),
      http.get(`${REG}/onboarding/sess-c`, () => HttpResponse.json(session())),
    );
    renderCopilot("/registry/onboard");

    // before the trigger + triage are set, Generate is disabled
    expect(screen.getByRole("button", { name: /generate process/i })).toBeDisabled();
    await fillAll(user);
    await waitFor(() => expect(screen.getByRole("button", { name: /generate process/i })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: /generate process/i }));

    await waitFor(() => expect(body).toBeDefined());
    expect(body!.bpmn_xml).toBe("<bpmn:definitions/>");
    expect((body!.mcp as { endpoint: string }).endpoint).toBe("http://mcp.local/mcp");
    expect(body!.pack_key).toBe("my-process");
    expect((body!.trigger as Record<string, unknown>).order_type).toBe("dine_in");   // user-provided trigger
    const rules = body!.triage_rules as Array<{ when: Record<string, unknown> }>;
    expect(rules).toHaveLength(1);
    expect(rules[0]!.when).toEqual({ field: "order_type", op: "eq", value: "dine_in" });   // user-provided triage
  });

  it("the triage field picker lists the parsed trigger fields; invalid trigger JSON blocks Generate", async () => {
    const user = userEvent.setup();
    renderCopilot("/registry/onboard");
    await user.upload(screen.getByLabelText("BPMN file"),
      new File(["<x/>"], "p.bpmn", { type: "application/xml" }));
    await user.type(screen.getByLabelText(/tools \(MCP/i), "http://mcp.local/mcp");

    // invalid JSON → inline error + Generate blocked
    fireEvent.change(screen.getByLabelText(/trigger event or schema/i), { target: { value: "{ not json" } });
    expect(await screen.findByText(/isn't valid json/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /generate process/i })).toBeDisabled();

    // valid sample → the triage field picker offers the parsed fields
    fireEvent.change(screen.getByLabelText(/trigger event or schema/i),
      { target: { value: JSON.stringify({ order_type: "dine_in", table: "5" }) } });
    await user.click(await screen.findByRole("button", { name: /add rule/i }));
    const fieldPicker = screen.getByLabelText("Trigger field") as HTMLSelectElement;
    const options = Array.from(fieldPicker.options).map((o) => o.value);
    expect(options).toEqual(expect.arrayContaining(["order_type", "table"]));
  });

  it("renders a friendly error when generation returns 502 copilot_llm_unavailable", async () => {
    const user = userEvent.setup();
    server.use(http.post(`${REG}/onboarding/copilot/generate`, () =>
      HttpResponse.json({ detail: { error: "copilot_llm_unavailable", message: "no ref" } }, { status: 502 })));
    renderCopilot("/registry/onboard");

    await fillAll(user);
    await user.click(screen.getByRole("button", { name: /generate process/i }));

    expect(await screen.findByText(/model isn't reachable/i)).toBeInTheDocument();
    expect(screen.queryByText(/copilot_llm_unavailable/)).not.toBeInTheDocument();   // no raw jargon
  });

  it("uses the wider onboarding layout", () => {
    renderCopilot("/registry/onboard");
    expect(document.querySelector(".max-w-6xl")).toBeInTheDocument();
  });
});

describe("Copilot flow — Review", () => {
  afterEach(() => server.resetHandlers());

  it("renders the plain-language summary, humanized gates, open questions, and enables go-live when clean", async () => {
    server.use(http.get(`${REG}/onboarding/sess-c`, () => HttpResponse.json(session())));
    renderCopilot("/registry/onboard/sess-c");

    expect(await screen.findByText(/when a party is seated/i)).toBeInTheDocument();      // summary
    // humanized gates — a side-effect gate reads as an AUTHORIZE sentence (generic mode→verb + id humanization)
    expect(screen.getByText(/kitchen authorizes fire ticket\./i)).toBeInTheDocument();
    expect(screen.getByText(/diner handles select items\./i)).toBeInTheDocument();
    expect(screen.getByText(/authorizes a real-world action/i)).toBeInTheDocument();     // side-effect badge
    // no raw ids / modes leak
    expect(screen.queryByText(/Task_FireTicket/)).not.toBeInTheDocument();
    expect(screen.queryByText(/approve_actions/)).not.toBeInTheDocument();
    // open question surfaced
    expect(screen.getByText(/should dine-in tickets route/i)).toBeInTheDocument();
    // readiness + enabled go-live
    expect(screen.getByText(/ready to go live/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /approve & go live/i })).toBeEnabled();
  });

  it("disables go-live and shows the problem in business language when validation has errors", async () => {
    server.use(http.get(`${REG}/onboarding/sess-c`, () => HttpResponse.json(session({
      dry_run_report: { pack_key: "rest-stan", pack_version: "1.0.0", created_at: "",
        findings: [{ code: "binding_input_unproduced", severity: "error", stage: 5,
                     message: "an input has no upstream source", element_id: "Task_ValidateOrder" }] },
    }))));
    renderCopilot("/registry/onboard/sess-c");

    expect(await screen.findByText(/not ready to go live yet/i)).toBeInTheDocument();
    expect(screen.getByText(/an input has no upstream source/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /approve & go live/i })).toBeDisabled();
  });

  it("links to the technical inspection wizard for the same session", async () => {
    server.use(http.get(`${REG}/onboarding/sess-c`, () => HttpResponse.json(session())));
    renderCopilot("/registry/onboard/sess-c");
    const link = await screen.findByRole("link", { name: /view \/ edit technical detail/i });
    expect(link).toHaveAttribute("href", "/registry/onboard/technical/sess-c");
  });

  it("humanizes generically — a wire-transfer (non-restaurant) session renders correct gate sentences", async () => {
    server.use(http.get(`${REG}/onboarding/sess-c`, () => HttpResponse.json(session({
      basics: { pack_key: "wire-repair", version: "1.0.0", title: "Wire repair", default_domain: "payments" },
      copilot_report: { summary: "A wire exception is triaged and repaired.", decisions: [], open_questions: [],
                        llm_used: true, model_ref: null, repair_passes: 0 },
      bindings: [
        binding({ element_id: "Task_ApproveRepair", executor_type: "human", role: "role.payments.ops_approver",
                  hitl_mode: "approve_actions", hitl_role: "role.payments.ops_approver" }),
        binding({ element_id: "Task_AssessRepairability", capability_ref: "cap.payments.assess@^1.0.0",
                  hitl_mode: "review_after", hitl_role: "role.payments.ops_analyst" }),
      ],
    }))));
    renderCopilot("/registry/onboard/sess-c");

    expect(await screen.findByText(/ops approver authorizes approve repair\./i)).toBeInTheDocument();
    expect(screen.getByText(/ops analyst reviews assess repairability\./i)).toBeInTheDocument();
  });
});

describe("Copilot flow — Chat", () => {
  afterEach(() => server.resetHandlers());

  it("sends a message, appends the turn, and shows a plain-language change", async () => {
    const user = userEvent.setup();
    const updated = session({
      conversation: [{ message: "the manager should approve firing, not the kitchen",
                       reply: "Done — the Manager now authorizes firing.", needs_clarification: false, changes: [] }],
      bindings: [binding({ element_id: "Task_FireTicket", hitl_mode: "approve_actions", hitl_role: "role.rest_stan.manager" })],
    });
    server.use(
      http.get(`${REG}/onboarding/sess-c`, () => HttpResponse.json(session())),
      http.post(`${REG}/onboarding/sess-c/copilot/chat`, () => HttpResponse.json({
        reply: "Done — the Manager now authorizes firing.", needs_clarification: false,
        changes: [{ element_id: "Task_FireTicket", field: "hitl_role",
                    before: "role.rest_stan.kitchen", after: "role.rest_stan.manager" }],
        report: updated.copilot_report, validation: updated.dry_run_report, session: updated,
      })),
    );
    renderCopilot("/registry/onboard/sess-c");
    await screen.findByText(/when a party is seated/i);

    await user.type(screen.getByLabelText(/refine message/i), "the manager should approve firing, not the kitchen");
    await user.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText(/the Manager now authorizes firing/i)).toBeInTheDocument();
    // a plain-language change line — not raw field/id
    expect(screen.getByText(/who is responsible/i)).toBeInTheDocument();
    expect(screen.getByText(/Fire ticket/)).toBeInTheDocument();
    // the summary re-derives from the refreshed session (gate now names the Manager)
    await waitFor(() => expect(screen.getByText(/manager authorizes fire ticket\./i)).toBeInTheDocument());
  });

  it("renders a needs_clarification reply as a question and applies no change", async () => {
    const user = userEvent.setup();
    const getSpy = vi.fn(() => HttpResponse.json(session()));
    server.use(
      http.get(`${REG}/onboarding/sess-c`, getSpy),
      http.post(`${REG}/onboarding/sess-c/copilot/chat`, () => HttpResponse.json({
        reply: "Which step would you like to make safer?", needs_clarification: true, changes: [],
        report: session().copilot_report, validation: session().dry_run_report, session: session(),
      })),
    );
    renderCopilot("/registry/onboard/sess-c");
    await screen.findByText(/when a party is seated/i);

    await user.type(screen.getByLabelText(/refine message/i), "make it safer");
    await user.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText(/which step would you like to make safer/i)).toBeInTheDocument();
    // still ready to go live — nothing destructive happened
    const readiness = screen.getByText(/ready to go live/i);
    expect(readiness).toBeInTheDocument();
  });
});

describe("Copilot flow — default front door", () => {
  afterEach(() => server.resetHandlers());

  it("is the /registry/onboard entry (the Start surface), not the technical wizard", () => {
    renderCopilot("/registry/onboard");
    expect(screen.getByRole("button", { name: /generate process/i })).toBeInTheDocument();
    expect(screen.getByText(/upload your process diagram/i)).toBeInTheDocument();
    expect(within(document.body).queryByText("TECHNICAL INSPECTION WIZARD")).not.toBeInTheDocument();
  });
});
