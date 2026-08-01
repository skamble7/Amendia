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

  it("lands pre-filled: summary in the rail, humanized gates on Understanding; go-live on the Review step", async () => {
    const user = userEvent.setup();
    server.use(http.get(`${REG}/onboarding/sess-c`, () => HttpResponse.json(session())));
    renderCopilot("/registry/onboard/sess-c");

    // the plain-language summary is in the persistent rail; humanized gates pre-fill the Understanding step
    expect(await screen.findByText(/when a party is seated/i)).toBeInTheDocument();      // summary (rail)
    expect(screen.getByText(/kitchen authorizes fire ticket\./i)).toBeInTheDocument();   // AUTHORIZE gate sentence
    expect(screen.getByText(/diner handles select items\./i)).toBeInTheDocument();
    // no raw ids / modes leak
    expect(screen.queryByText(/Task_FireTicket/)).not.toBeInTheDocument();
    expect(screen.queryByText(/approve_actions/)).not.toBeInTheDocument();

    // the Review & go live step carries the open question, readiness, side-effect badge, and enabled approve
    await user.click(screen.getByRole("button", { name: /review & go live/i }));
    expect(await screen.findByText(/should dine-in tickets route/i)).toBeInTheDocument();
    expect(screen.getByText(/authorizes a real-world action/i)).toBeInTheDocument();
    expect(screen.getByText(/ready to go live/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /approve & go live/i })).toBeEnabled();
  });

  it("gates go-live on clean validation — errors disable Approve on the Review step", async () => {
    const user = userEvent.setup();
    server.use(http.get(`${REG}/onboarding/sess-c`, () => HttpResponse.json(session({
      dry_run_report: { pack_key: "rest-stan", pack_version: "1.0.0", created_at: "",
        findings: [{ code: "binding_input_unproduced", severity: "error", stage: 5,
                     message: "an input has no upstream source", element_id: "Task_ValidateOrder" }] },
    }))));
    renderCopilot("/registry/onboard/sess-c");
    await user.click(await screen.findByRole("button", { name: /review & go live/i }));

    expect(await screen.findByText(/not ready to go live yet/i)).toBeInTheDocument();
    expect(screen.getByText(/an input has no upstream source/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /approve & go live/i })).toBeDisabled();
  });

  it("links to the technical inspection wizard for the same session (Review step)", async () => {
    const user = userEvent.setup();
    server.use(http.get(`${REG}/onboarding/sess-c`, () => HttpResponse.json(session())));
    renderCopilot("/registry/onboard/sess-c");
    await user.click(await screen.findByRole("button", { name: /review & go live/i }));
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
    // nothing destructive happened — the draft is unchanged (the gate still reads the same)
    expect(screen.getByText(/kitchen authorizes fire ticket\./i)).toBeInTheDocument();
  });
});

describe("Copilot flow — stepped review + schema refiner (ADR-054)", () => {
  afterEach(() => server.resetHandlers());

  // a domain-neutral wire session with a human-authored artifact whose DERIVED schema is loose (an opaque object).
  function wireSession(over: Record<string, unknown> = {}) {
    return session({
      basics: { pack_key: "wire-repair", version: "1.0.0", title: "Wire repair", default_domain: "payments" },
      copilot_report: { summary: "A wire exception is triaged and repaired.", decisions: [], open_questions: [],
                        llm_used: true, model_ref: null, repair_passes: 0 },
      inferred: { roles: [{ role_id: "role.payments.ops_approver", label: "Ops Approver", source_lane: "L1", description: null }],
                  bindings: [], gateway_variables: [], capability_candidates: [], artifact_seeds: [], sod_candidates: [], annotations: [] },
      staged_artifacts: [{ artifact_key: "art.payments.wire_exception", version: "1.0.0", title: "Wire exception", json_schema: { type: "object", properties: {} } }],
      authored_artifacts: [{ artifact_key: "art.payments.approved_repair", version: "1.0.0", title: "Approved repair",
        json_schema: { type: "object", properties: { decision: { type: "object" } }, required: ["decision"] } }],
      bindings: [
        binding({ element_id: "Task_ApproveRepair", executor_type: "human", role: "role.payments.ops_approver",
                  hitl_mode: "manual", hitl_role: "role.payments.ops_approver",
                  outputs: [{ name: "approved_repair", schema_ref: "art.payments.approved_repair@^1.0.0", required: true }] }),
      ],
      ...over,
    });
  }

  it("lands pre-filled: the Understanding step shows the inferred roles + gates, summary in the rail", async () => {
    server.use(http.get(`${REG}/onboarding/sess-c`, () => HttpResponse.json(wireSession())));
    renderCopilot("/registry/onboard/sess-c");
    expect(await screen.findByText(/roles \(from the diagram lanes\)/i)).toBeInTheDocument(); // inferred roles section
    expect(screen.getByText(/ops approver handles approve repair\./i)).toBeInTheDocument();   // human gate
    expect(screen.getByText(/a wire exception is triaged/i)).toBeInTheDocument();             // summary (rail)
  });

  it("the schema refiner re-types a property + adds a label → the live preview shows a labeled field, and Save persists the concrete schema", async () => {
    const user = userEvent.setup();
    let refineBody: Record<string, unknown> | undefined;
    server.use(
      http.get(`${REG}/onboarding/sess-c`, () => HttpResponse.json(wireSession())),
      http.put(`${REG}/onboarding/sess-c/artifacts/refine`, async ({ request }) => {
        refineBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(wireSession());
      }),
    );
    renderCopilot("/registry/onboard/sess-c");

    await user.click(await screen.findByRole("button", { name: /artifacts & schemas/i }));
    // the human-authored artifact's refiner is pre-filled with its derived property
    expect(await screen.findByLabelText(/property 0 name/i)).toHaveValue("decision");

    // re-type the opaque object → string, and label it; the live form preview reflects the edit
    fireEvent.change(screen.getByLabelText(/property 0 type/i), { target: { value: "string" } });
    fireEvent.change(screen.getByLabelText(/property 0 label/i), { target: { value: "Decision outcome" } });
    expect(await screen.findByText("Decision outcome")).toBeInTheDocument();   // rendered as a labeled field, not raw JSON

    // Save → the refine endpoint receives the refined CONCRETE schema (typed + titled)
    await user.click(screen.getByRole("button", { name: /save schema/i }));
    await waitFor(() => expect(refineBody).toBeDefined());
    expect(refineBody!.artifact_key).toBe("art.payments.approved_repair");
    const schema = refineBody!.json_schema as { properties: { decision: { type: string; title?: string } } };
    expect(schema.properties.decision.type).toBe("string");
    expect(schema.properties.decision.title).toBe("Decision outcome");
  });

  it("the Capabilities step is read-mostly — the connected endpoint + staged caps show, with no second MCP URL entry", async () => {
    const user = userEvent.setup();
    const cap = (over: Record<string, unknown>) => ({
      capability_id: "cap.payments.x", kind: "mcp", endpoint: "http://wirefix-mcp:8060/mcp", transport: "streamable_http",
      input_artifact_key: "art.payments.in", input_name: "in", output_artifact_key: "art.payments.out", output_name: "out",
      side_effect: "read_only", ...over,
    });
    server.use(http.get(`${REG}/onboarding/sess-c`, () => HttpResponse.json(wireSession({
      staged_capabilities: [
        cap({ capability_id: "cap.payments.assess", tool: "assess_beneficiary" }),
        cap({ capability_id: "cap.payments.apply", tool: "apply_repair", side_effect: "side_effectful" }),
      ],
    }))));
    renderCopilot("/registry/onboard/sess-c");

    await user.click(await screen.findByRole("button", { name: /Capabilities/i }));
    // the endpoint is shown as read-only text, NOT a pre-filled URL input to re-enter
    expect(await screen.findByText("http://wirefix-mcp:8060/mcp")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("http://wirefix-mcp:8060/mcp")).toBeNull();
    // the discovered capabilities + the side-effect flag are shown; re-introspect is optional
    expect(screen.getByText("assess_beneficiary")).toBeInTheDocument();
    expect(screen.getByText("apply_repair")).toBeInTheDocument();
    expect(screen.getByText(/real-world effect/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /re-introspect/i })).toBeInTheDocument();
  });

  it("a copilot-seeded human artifact renders its baseline fields with a 'drafted by the copilot' hint", async () => {
    const user = userEvent.setup();
    server.use(http.get(`${REG}/onboarding/sess-c`, () => HttpResponse.json(wireSession({
      authored_artifacts: [{
        artifact_key: "art.payments.escalation_decision", version: "1.0.0", title: "Escalation decision",
        json_schema: { type: "object", additionalProperties: false, required: ["decision"], properties: {
          decision: { type: "string", title: "Decision", enum: ["escalate", "hold", "close"] },
          notes: { type: "string", title: "Notes" } } },
      }],
      copilot_report: {
        summary: "A wire exception is triaged and repaired.", open_questions: [], llm_used: true, model_ref: null, repair_passes: 0,
        decisions: [{ kind: "human_artifact", element_id: null, decided_by: "deterministic",
          summary: "seeded a baseline schema for art.payments.escalation_decision (decision, notes) from process context — copilot draft, review in the refiner" }],
      },
    }))));
    renderCopilot("/registry/onboard/sess-c");

    await user.click(await screen.findByRole("button", { name: /artifacts & schemas/i }));
    // the baseline fields render as a labeled form (not an empty refiner) + the draft hint
    expect(await screen.findByText("Decision")).toBeInTheDocument();          // the preview field label
    expect(screen.getByText(/drafted by the copilot/i)).toBeInTheDocument();
  });

  it("walking Continue through an unedited generated session reaches go-live with no ordering toast (triage before gateways)", async () => {
    const user = userEvent.setup();
    const setterCalls: string[] = [];
    const walkSession = wireSession({
      bpmn: { process_id: "P", bpmn_file: "p.bpmn", sha256: "x", required_execution_profile: "common_executable",
              bindable_elements: [], gateways: [], message_flows: [] },
    });
    server.use(
      http.get(`${REG}/onboarding/sess-c`, () => HttpResponse.json(walkSession)),
      http.get(`${REG}/capabilities`, () => HttpResponse.json([])),
      http.get(`${REG}/packs`, () => HttpResponse.json([])),
      http.put(`${REG}/onboarding/sess-c/bindings`, () => { setterCalls.push("bindings"); return HttpResponse.json(walkSession); }),
      http.put(`${REG}/onboarding/sess-c/triage`, () => { setterCalls.push("triage"); return HttpResponse.json(walkSession); }),
      http.put(`${REG}/onboarding/sess-c/policies`, () => { setterCalls.push("policies"); return HttpResponse.json(walkSession); }),
    );
    renderCopilot("/registry/onboard/sess-c");

    // the step order matches the engine: Trigger & triage precedes Gateways
    const triage = await screen.findByText("Trigger & triage");
    const gateways = screen.getByText("Gateways");
    // eslint-disable-next-line no-bitwise
    expect(triage.compareDocumentPosition(gateways) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    // Continue straight through all six transitions without editing anything
    for (let i = 0; i < 6; i++) {
      await user.click(await screen.findByRole("button", { name: "Continue" }));
    }

    // reached Review & go live — ready, and NO setter was re-invoked (no regress, no "set triage rules before policies")
    expect(await screen.findByRole("button", { name: /approve & go live/i })).toBeInTheDocument();
    expect(setterCalls).toEqual([]);
  });

  it("edit mode (ADR-056): the review frames as an edit and the final action publishes the new version via commit", async () => {
    const user = userEvent.setup();
    let committed = false;
    const editing = session({ basics: { pack_key: "wire-repair", version: "1.1.0", title: "Wire repair", default_domain: "payments" } });
    server.use(
      http.get(`${REG}/onboarding/sess-c`, () => HttpResponse.json(editing)),
      http.post(`${REG}/onboarding/sess-c/commit`, () => {
        committed = true;
        return HttpResponse.json(session({ state: "completed", result_pack: "wire-repair@1.1.0",
          basics: { pack_key: "wire-repair", version: "1.1.0", title: "Wire repair", default_domain: "payments" } }));
      }),
    );
    renderCopilot("/registry/onboard/sess-c?mode=edit");

    // the header frames it as an edit → new version (not a fresh review)
    expect(await screen.findByText(/Editing wire-repair/i)).toBeInTheDocument();
    expect(screen.getByText(/new version 1\.1\.0/i)).toBeInTheDocument();

    // the final step's action reads "Publish version 1.1.0" and calls the commit (publish) endpoint
    await user.click(await screen.findByRole("button", { name: /review & go live/i }));
    const publish = await screen.findByRole("button", { name: /publish version 1\.1\.0/i });
    await user.click(publish);
    await waitFor(() => expect(committed).toBe(true));
    expect(await screen.findByText(/your process is live/i)).toBeInTheDocument();   // publish succeeded
  });

  it("every step has a uniform Back/Continue footer; Continue advances", async () => {
    const user = userEvent.setup();
    server.use(http.get(`${REG}/onboarding/sess-c`, () => HttpResponse.json(wireSession())));
    renderCopilot("/registry/onboard/sess-c");

    // Understanding (first step): Continue present, no Back yet
    const cont = await screen.findByRole("button", { name: "Continue" });
    expect(cont).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Back" })).toBeNull();

    await user.click(cont);   // → Capabilities
    expect(await screen.findByText(/Connected tool server/i)).toBeInTheDocument();
    // the same footer, now with Back
    expect(screen.getByRole("button", { name: "Continue" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back" })).toBeInTheDocument();
  });

  it("the Trigger & triage step is a read-mostly confirmation with an Edit affordance, not the builder", async () => {
    const user = userEvent.setup();
    server.use(http.get(`${REG}/onboarding/sess-c`, () => HttpResponse.json(wireSession({
      trigger_artifact: { artifact_key: "art.payments.wire_exception", version: "1.0.0", title: "Wire exception",
        json_schema: { type: "object", properties: { exception_type: { type: "string" }, amount: { type: "number" } } } },
      triage_rules: [{ rule_id: "r1", priority: 100, when: { field: "exception_type", op: "eq", value: "unable_to_apply" } }],
    }))));
    renderCopilot("/registry/onboard/sess-c");

    await user.click(await screen.findByRole("button", { name: /Trigger & triage/i }));   // stepper
    // read-mostly confirmation: the trigger field count + each rule in plain form; an Edit affordance
    expect(await screen.findByText(/2 fields/i)).toBeInTheDocument();
    expect(screen.getByText("exception_type eq unable_to_apply")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();

    // Edit reveals the builder (which brings its own Save footer); the confirmation's Edit button is gone
    await user.click(screen.getByRole("button", { name: "Edit" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Edit" })).toBeNull());
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
