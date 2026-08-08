import { describe, it, expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderApp } from "@/test/renderApp";
import { server } from "@/test/server";
import { SERVICE_BASE } from "@/api/config";
import { synthPack, synthValidationReport } from "@/test/fixtures";

const REG = SERVICE_BASE.registry;

describe("Registry catalog", () => {
  it("lists packs from the registry", async () => {
    server.use(http.get(`${REG}/packs`, () => HttpResponse.json([synthPack])));
    renderApp("/registry", "owner-1");
    expect(await screen.findByText("Test Pack")).toBeInTheDocument();
    expect(await screen.findByText(/test-pack@1\.0\.0/)).toBeInTheDocument();
  });

  // ADR-060: capabilities & schemas moved off the global page onto the pack detail, fetched pack-scoped.
  it("a pack's detail page shows its OWNED capabilities and schemas (fetched pack-scoped)", async () => {
    const cap = {
      descriptor_version: "1.0", pack_key: "test-pack", pack_version: "1.0.0",
      capability_id: "cap.test.do", version: "1.0.0", title: "Do The Thing", kind: "mcp",
      side_effect: "read_only", inputs: [], outputs: [],
      runtime: { kind: "mcp", endpoint: "http://x", tools: ["t"] }, status: "active",
    };
    const schema = {
      pack_key: "test-pack", pack_version: "1.0.0", artifact_key: "art.test.out", version: "1.0.0",
      title: "Out Schema", json_schema: { type: "object", properties: { ok: { type: "boolean" } } }, status: "active",
    };
    // ADR-061 Phase 4: the pack-detail catalog reads hit the NESTED collection routes (not ?pack_key=…).
    let capNestedHit = false;
    server.use(
      http.get(`${REG}/packs/test-pack/1.0.0`, () => HttpResponse.json(synthPack)),
      http.get(`${REG}/packs/test-pack/1.0.0/bpmn`, () => HttpResponse.text("<bpmn/>")),
      http.get(`${REG}/packs/test-pack/1.0.0/resolution`, () => new HttpResponse(null, { status: 404 })),
      http.get(`${REG}/packs/test-pack/1.0.0/versions`, () => HttpResponse.json([synthPack])),
      http.get(`${REG}/packs/test-pack/1.0.0/capabilities`, () => { capNestedHit = true; return HttpResponse.json([cap]); }),
      http.get(`${REG}/packs/test-pack/1.0.0/artifact-schemas`, () => HttpResponse.json([schema])),
    );
    const user = userEvent.setup();
    renderApp("/registry/packs/test-pack/1.0.0", "owner-1");
    await screen.findByText("Test Pack");

    await user.click(await screen.findByRole("tab", { name: /capabilities/i }));
    expect(await screen.findByText("Do The Thing")).toBeInTheDocument();
    // the fetch used THIS pack version's nested route (no global/query-param catalog)
    expect(capNestedHit).toBe(true);

    await user.click(await screen.findByRole("tab", { name: /schemas/i }));
    expect(await screen.findByText("Out Schema")).toBeInTheDocument();
  });

  // ADR-061: pack deletion is owner-gated + confirmed, then invalidates + navigates back to /registry.
  it("an owner can delete a pack version — confirming hits DELETE and navigates away", async () => {
    let deleteHit = false;
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    server.use(
      http.get(`${REG}/packs/test-pack/1.0.0`, () => HttpResponse.json(synthPack)),
      http.get(`${REG}/packs/test-pack/1.0.0/bpmn`, () => HttpResponse.text("<bpmn/>")),
      http.get(`${REG}/packs/test-pack/1.0.0/resolution`, () => new HttpResponse(null, { status: 404 })),
      http.get(`${REG}/packs`, () => HttpResponse.json([synthPack])),
      http.delete(`${REG}/packs/test-pack/1.0.0`, () => {
        deleteHit = true;
        return HttpResponse.json({ pack_key: "test-pack", whole_pack: false, deleted_versions: ["1.0.0"], versions: [] });
      }),
    );
    const user = userEvent.setup();
    renderApp("/registry/packs/test-pack/1.0.0", "owner-1");
    await screen.findByText("Test Pack");

    await user.click(await screen.findByRole("button", { name: /delete version/i }));
    expect(confirmSpy).toHaveBeenCalled();
    await waitFor(() => expect(deleteHit).toBe(true));
    // navigated back to /registry — the pack-detail-only Delete action is gone
    await waitFor(() => expect(screen.queryByRole("button", { name: /delete version/i })).not.toBeInTheDocument());
    confirmSpy.mockRestore();
  });

  it("a non-owner does not see the delete action on the pack detail", async () => {
    server.use(
      http.get(`${REG}/packs/test-pack/1.0.0`, () => HttpResponse.json(synthPack)),
      http.get(`${REG}/packs/test-pack/1.0.0/bpmn`, () => HttpResponse.text("<bpmn/>")),
      http.get(`${REG}/packs/test-pack/1.0.0/resolution`, () => new HttpResponse(null, { status: 404 })),
    );
    // analyst-1 holds role.payments.ops_analyst only — no role.process.owner.
    renderApp("/registry/packs/test-pack/1.0.0", "analyst-1");
    await screen.findByText("Test Pack");
    expect(screen.queryByRole("button", { name: /delete version/i })).not.toBeInTheDocument();
  });

  it("the global Registry page no longer has Capabilities/Schemas tabs", async () => {
    server.use(http.get(`${REG}/packs`, () => HttpResponse.json([synthPack])));
    renderApp("/registry", "owner-1");
    await screen.findByText("Test Pack");
    expect(screen.queryByRole("tab", { name: /capabilities/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /schemas/i })).not.toBeInTheDocument();
  });
});

describe("Onboarding wizard", () => {
  it("start screen offers a new-pack form", async () => {
    server.use(http.get(`${REG}/onboarding`, () => HttpResponse.json([])));
    renderApp("/registry/onboard", "owner-1");
    expect(await screen.findByText(/New pack/i)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /create & continue/i })).toBeInTheDocument();
  });

  it("review step groups the dry-run error under its stage and blocks activation", async () => {
    const session = {
      session_id: "sess-1", created_by: "owner-1", created_at: "", updated_at: "", state: "assembled",
      basics: { pack_key: "p", version: "1.0.0", title: "P", default_domain: "payment" },
      bpmn: { process_id: "proc", bpmn_file: "p.bpmn", sha256: "x", bindable_elements: [{ element_id: "T", element_kind: "serviceTask", category: "capability", name: "T", is_multi_instance: false, is_for_compensation: false, compensation_primary: null, in_event_subprocess: false }], service_tasks: ["T"], user_tasks: [], gateways: [], task_names: {} },
      staged_artifacts: [], staged_capabilities: [], reused_capability_refs: [], bindings: [],
      triage_rules: [], gateway_variables: [], sod_policies: [], roles: [],
      dry_run_report: synthValidationReport, commit_progress: [], result_pack: null, last_cleared: [],
    };
    server.use(http.get(`${REG}/onboarding/sess-1`, () => HttpResponse.json(session)));
    renderApp("/registry/onboard/sess-1", "owner-1");

    expect(await screen.findByText(/test_side_effect_error/)).toBeInTheDocument();
    expect(await screen.findByText(/HITL & side-effect policy/)).toBeInTheDocument();
    const activate = await screen.findByRole("button", { name: /activate pack/i });
    expect(activate).toBeDisabled();
  });

  it("bindings step authors the full bindable set with per-category sub-forms (ADR-044)", async () => {
    const be = (over: Record<string, unknown>) => ({
      name: null, is_multi_instance: false, is_for_compensation: false,
      compensation_primary: null, in_event_subprocess: false, ...over,
    });
    const session = {
      session_id: "sess-3", created_by: "owner-1", created_at: "", updated_at: "", state: "bindings_set",
      basics: { pack_key: "p", version: "1.0.0", title: "P", default_domain: "payment" },
      bpmn: {
        process_id: "P", bpmn_file: "p.bpmn", sha256: "x",
        service_tasks: ["Svc"], user_tasks: ["Usr"], gateways: [], task_names: {},
        bindable_elements: [
          be({ element_id: "Svc", element_kind: "serviceTask", category: "capability", name: "Screen" }),
          be({ element_id: "Usr", element_kind: "userTask", category: "human", name: "Approve" }),
          be({ element_id: "Recv", element_kind: "receiveTask", category: "message", name: "Await reply", message_name: "pay.reply" }),
          be({ element_id: "CallSub", element_kind: "callActivity", category: "call", name: "Sub-pack", called_pack: "other-pack", called_version: "^1.0.0" }),
        ],
      },
      staged_artifacts: [], reused_capability_refs: [], bindings: [],
      staged_capabilities: [{ capability_id: "cap.payment.screen", version: "1.0.0", title: "Screen", side_effect: "read_only", input_name: "in", input_artifact_key: "art.payment.in", output_name: "out", output_artifact_key: "art.payment.out", endpoint: "http://x", tool: "screen", transport: "streamable_http", headers: {} }],
      triage_rules: [], gateway_variables: [], sod_policies: [], roles: [],
      dry_run_report: null, commit_progress: [], result_pack: null, last_cleared: [], inferred: null,
    };
    server.use(
      http.get(`${REG}/onboarding/sess-3`, () => HttpResponse.json(session)),
      http.get(`${REG}/capabilities`, () => HttpResponse.json([])),
      http.get(`${REG}/packs`, () => HttpResponse.json([synthPack])),
    );
    renderApp("/registry/onboard/sess-3", "owner-1");

    // the full bindable set is listed (capability + human + message + call)
    expect(await screen.findByText("Recv")).toBeInTheDocument();
    expect(await screen.findByText("CallSub")).toBeInTheDocument();
    // message executor sub-form (message name, no HITL)
    expect(await screen.findByText("Message name")).toBeInTheDocument();
    // call executor sub-form (callee pack picker + IO maps)
    expect(await screen.findByText("Callee pack")).toBeInTheDocument();
    expect(await screen.findByText(/Input map/)).toBeInTheDocument();
  });

  it("bindings step lets a human task declare read-only inputs sourced from an upstream output (ADR-048)", async () => {
    const be = (over: Record<string, unknown>) => ({
      name: null, is_multi_instance: false, is_for_compensation: false,
      compensation_primary: null, in_event_subprocess: false, ...over,
    });
    const session = {
      session_id: "sess-hin", created_by: "owner-1", created_at: "", updated_at: "", state: "bindings_set",
      basics: { pack_key: "p", version: "1.0.0", title: "P", default_domain: "dining" },
      bpmn: {
        process_id: "P", bpmn_file: "p.bpmn", sha256: "x",
        service_tasks: ["PresentMenu"], user_tasks: ["SelectItems"], gateways: [], task_names: {},
        bindable_elements: [
          be({ element_id: "PresentMenu", element_kind: "serviceTask", category: "capability", name: "Present menu" }),
          be({ element_id: "SelectItems", element_kind: "userTask", category: "human", name: "Select items" }),
        ],
      },
      staged_artifacts: [{ artifact_key: "art.dining.get_menu_output", version: "1.0.0", title: "Menu", json_schema: {} }],
      reused_capability_refs: [], bindings: [],
      staged_capabilities: [{ capability_id: "cap.dining.get_menu", version: "1.0.0", title: "Get menu", side_effect: "read_only", input_name: "get_menu_input", input_artifact_key: "art.dining.get_menu_input", output_name: "get_menu_output", output_artifact_key: "art.dining.get_menu_output", endpoint: "http://x", tool: "get_menu", transport: "streamable_http", headers: {} }],
      triage_rules: [], gateway_variables: [], sod_policies: [], roles: [], dry_run_report: null,
      commit_progress: [], result_pack: null, last_cleared: [], inferred: null,
    };
    server.use(
      http.get(`${REG}/onboarding/sess-hin`, () => HttpResponse.json(session)),
      http.get(`${REG}/capabilities`, () => HttpResponse.json([])),
      http.get(`${REG}/packs`, () => HttpResponse.json([synthPack])),
    );
    renderApp("/registry/onboard/sess-hin", "owner-1");

    const user = userEvent.setup();
    // the human task now carries an INPUTS editor (read-only context) — previously only capability tasks did
    expect(await screen.findByText(/read-only context artifact/i)).toBeInTheDocument();
    const addInput = await screen.findByRole("button", { name: /add input/i });
    await user.click(addInput);
    // an input row appears and is interactive; naming it reveals its per-input SOURCE picker
    const nameField = await screen.findByPlaceholderText("menu");
    await user.type(nameField, "menu");
    // the upstream-output source option is offered (present for the human input's picker now that it exists)
    expect(screen.getAllByRole("option", { name: /upstream output/i }).length).toBeGreaterThan(0);
  });

  it("policies step shows SoD candidates with their rationale + seeds persona descriptions (ADR-045)", async () => {
    const be = (id: string) => ({ element_id: id, element_kind: "serviceTask", category: "capability", name: id, is_multi_instance: false, is_for_compensation: false, compensation_primary: null, in_event_subprocess: false });
    const session = {
      session_id: "sess-4", created_by: "owner-1", created_at: "", updated_at: "", state: "policies_set",
      basics: { pack_key: "p", version: "1.0.0", title: "P", default_domain: "payment" },
      bpmn: {
        process_id: "P", bpmn_file: "p.bpmn", sha256: "x", service_tasks: ["Draft", "Approve"], user_tasks: [],
        gateways: [], task_names: {}, bindable_elements: [be("Draft"), be("Approve")],
      },
      staged_artifacts: [], staged_capabilities: [], reused_capability_refs: [], bindings: [],
      triage_rules: [], gateway_variables: [], sod_policies: [], roles: ["role.payment.ops_approver"],
      inferred: {
        roles: [{ role_id: "role.payment.ops_approver", label: "Ops Approver", source_lane: "L", description: "Four-eyes approver — authorizes side-effectful actions before they execute." }],
        bindings: [], gateway_variables: [], capability_candidates: [], artifact_seeds: [], annotations: [],
        sod_candidates: [{ elements: ["Draft", "Approve"], rationale: "'Draft repair' and 'Approve repair' are in different lanes — four-eyes candidate" }],
      },
      dry_run_report: null, commit_progress: [], result_pack: null, last_cleared: [],
    };
    server.use(
      http.get(`${REG}/onboarding/sess-4`, () => HttpResponse.json(session)),
      http.get(`${REG}/capabilities`, () => HttpResponse.json([])),
    );
    renderApp("/registry/onboard/sess-4", "owner-1");
    // the SoD candidate carries its rationale as a "suggested" provenance chip
    expect(await screen.findByText(/four-eyes candidate/i)).toBeInTheDocument();
    // the lane persona description is pre-filled into role_meta (editable)
    expect(await screen.findByDisplayValue(/Four-eyes approver/i)).toBeInTheDocument();
  });

  it("capabilities step surfaces external integrations from message flows (ADR-045)", async () => {
    const session = {
      session_id: "sess-5", created_by: "owner-1", created_at: "", updated_at: "", state: "capabilities_resolved",
      basics: { pack_key: "p", version: "1.0.0", title: "P", default_domain: "payment" },
      bpmn: {
        process_id: "P", bpmn_file: "p.bpmn", sha256: "x", service_tasks: [], user_tasks: [],
        gateways: [], task_names: {}, bindable_elements: [],
        message_flows: [{ id: "mf1", name: "Sanctions Provider", source: "a", target: "b" }],
      },
      staged_artifacts: [], staged_capabilities: [], reused_capability_refs: [], bindings: [],
      triage_rules: [], gateway_variables: [], sod_policies: [], roles: [],
      inferred: {
        roles: [], bindings: [], gateway_variables: [], artifact_seeds: [], sod_candidates: [],
        capability_candidates: [{ source: "mf1", suggested_capability_id: "cap.payment.sanctions_provider", kind_hint: "mcp", needs_endpoint: true }],
        annotations: [{ code: "external_integration_hint", element_id: "mf1", message: "message flow 'Sanctions Provider' — external-system integration" }],
      },
      dry_run_report: null, commit_progress: [], result_pack: null, last_cleared: [],
    };
    server.use(
      http.get(`${REG}/onboarding/sess-5`, () => HttpResponse.json(session)),
      http.get(`${REG}/capabilities`, () => HttpResponse.json([])),
    );
    renderApp("/registry/onboard/sess-5", "owner-1");
    expect(await screen.findByText(/External integrations/i)).toBeInTheDocument();
    expect(await screen.findByText("Sanctions Provider")).toBeInTheDocument();
    expect(await screen.findByText(/likely cap\.payment\.sanctions_provider/)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Introspect for this/i })).toBeInTheDocument();
  });

  it("capabilities step authors a decision table + surfaces inline dmn validation (ADR-046)", async () => {
    const session = {
      session_id: "sess-6", created_by: "owner-1", created_at: "", updated_at: "", state: "capabilities_resolved",
      basics: { pack_key: "p", version: "1.0.0", title: "P", default_domain: "payment" },
      bpmn: {
        process_id: "P", bpmn_file: "p.bpmn", sha256: "x", service_tasks: [], user_tasks: [],
        gateways: [], task_names: {}, bindable_elements: [], message_flows: [],
      },
      staged_artifacts: [{ artifact_key: "art.payment.enriched", version: "1.0.0", title: "e", json_schema: {} }],
      staged_capabilities: [], reused_capability_refs: [], bindings: [],
      triage_rules: [], gateway_variables: [], sod_policies: [], roles: [],
      inferred: { roles: [], bindings: [], gateway_variables: [], capability_candidates: [], artifact_seeds: [], sod_candidates: [], annotations: [] },
      dry_run_report: null, commit_progress: [], result_pack: null, last_cleared: [],
    };
    server.use(
      http.get(`${REG}/onboarding/sess-6`, () => HttpResponse.json(session)),
      http.get(`${REG}/capabilities`, () => HttpResponse.json([])),
      http.post(`${REG}/onboarding/sess-6/capabilities`, () => HttpResponse.json(
        { error: "capabilities_invalid", errors: [{ capability_id: "cap.payment.bad", field: "table", code: "dmn_bad_unary_test", message: "rule 0 input cell 0 is not a legal unary test" }] },
        { status: 422 })),
    );
    const user = userEvent.setup();
    renderApp("/registry/onboard/sess-6", "owner-1");

    // open the DMN builder → its grid controls render
    await user.click(await screen.findByRole("button", { name: /Decision table/i }));
    const capId = await screen.findByPlaceholderText("cap.payment.classify");
    expect(capId).toBeInTheDocument();
    // adding an input column grows the rule grid
    const inputsBefore = screen.getAllByPlaceholderText(/gpi_status/).length;
    await user.click(screen.getByRole("button", { name: /^input$/i }));
    expect(screen.getAllByPlaceholderText(/gpi_status/).length).toBe(inputsBefore + 1);
    // name it + submit → the server's dmn_* finding surfaces inline on the builder
    await user.type(capId, "cap.payment.bad");
    await user.click(screen.getByRole("button", { name: /Save & continue/i }));
    expect(await screen.findByText(/not a legal unary test/i)).toBeInTheDocument();
  });

  it("accepts full BPMN and shows a coverage report with documented elements (ADR-027)", async () => {
    const base = {
      session_id: "sess-2", created_by: "owner-1", created_at: "", updated_at: "",
      basics: { pack_key: "p", version: "1.0.0", title: "P", default_domain: "payment" },
      staged_artifacts: [], staged_capabilities: [], reused_capability_refs: [], bindings: [],
      triage_rules: [], gateway_variables: [], sod_policies: [], roles: [],
      dry_run_report: null, commit_progress: [], result_pack: null, last_cleared: [],
    };
    const initiated = { ...base, state: "initiated", bpmn: null };
    const attached = {
      ...base, state: "bpmn_attached",
      bpmn: {
        process_id: "P", bpmn_file: "p.bpmn", sha256: "x",
        bindable_elements: [{ element_id: "T", element_kind: "userTask", category: "human", name: "Approve", is_multi_instance: false, is_for_compensation: false, compensation_primary: null, in_event_subprocess: false }],
        service_tasks: [], user_tasks: ["T"], gateways: [], task_names: {},
        documented_elements: [
          { element_id: "B1", kind: "boundaryEvent", tier: "documented" },
          { element_id: "LS", kind: "laneSet", tier: "documented" },
        ],
        coverage_counts: { executable: 3, documented: 2, unknown: 0 },
        required_execution_profile: "common_executable",
        subprocesses: [{ id: "Sub", name: "Repair sub-process", member_ids: ["T"] }],
        lanes: [{ id: "L1", name: "Ops Analyst", member_ids: ["T"] }],
      },
      inferred: {
        roles: [{ role_id: "role.payment.ops_analyst", label: "Ops Analyst", source_lane: "L1" }],
        bindings: [{ element_id: "T", element_kind: "userTask", executor_type: "human", suggested_role: "role.payment.ops_analyst", suggested_hitl_mode: "manual", source_lane: "L1" }],
        gateway_variables: [], capability_candidates: [], artifact_seeds: [], sod_candidates: [],
        annotations: [{ code: "sla_escalation_hint", element_id: "B1", message: "'SLA breach' (boundaryEvent/timer) — SLA / escalation policy hint" }],
      },
    };
    server.use(
      http.get(`${REG}/onboarding/sess-2`, () => HttpResponse.json(initiated)),
      http.put(`${REG}/onboarding/sess-2/bpmn`, () => HttpResponse.json(attached)),
    );
    const user = userEvent.setup();
    renderApp("/registry/onboard/sess-2", "owner-1");

    // Basics → BPMN, then paste + parse.
    await user.click(await screen.findByRole("button", { name: /continue to bpmn/i }));
    await user.type(await screen.findByPlaceholderText(/paste <bpmn/i), "abc");
    await user.click(screen.getByRole("button", { name: /parse & preview coverage/i }));

    // Coverage report: it was ACCEPTED (not rejected) and lists documented elements.
    expect(await screen.findByText(/Coverage · P/)).toBeInTheDocument();
    // ADR-027 Phase 2.5: a diagram with parallel gateways flags its required execution profile.
    expect(screen.getByText(/Requires common_executable/i)).toBeInTheDocument();
    // ADR-032 Phase 2.6: embedded sub-processes render as an executable group.
    expect(screen.getByText(/Repair sub-process/)).toBeInTheDocument();
    expect(screen.getByText(/Sub-processes ·/)).toBeInTheDocument();
    expect(screen.getByText(/Documented — not executed today/i)).toBeInTheDocument();
    expect(screen.getByText(/boundaryEvent · B1/)).toBeInTheDocument();
    expect(screen.queryByText(/BPMN rejected/i)).not.toBeInTheDocument();
    // Phase 1: the inference panel summarizes what was derived from the diagram + advisory hints.
    expect(screen.getByText(/Inferred from your diagram/i)).toBeInTheDocument();
    expect(screen.getByText(/SLA \/ escalation policy hint/i)).toBeInTheDocument();

    // Batch-1 UX: after a successful parse the tall input collapses to a one-line summary (the paste
    // box is gone); "Replace / edit" re-expands it.
    expect(screen.getByText(/BPMN attached/i)).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/paste <bpmn/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Replace \/ edit/i }));
    expect(await screen.findByPlaceholderText(/paste <bpmn/i)).toBeInTheDocument();
  });

  it("bindings step pre-selects the inferred capability + fixes HITL floor/role (batch-2)", async () => {
    const be = (over: Record<string, unknown>) => ({
      name: null, is_multi_instance: false, is_for_compensation: false,
      compensation_primary: null, in_event_subprocess: false, ...over,
    });
    const session = {
      session_id: "sess-8", created_by: "owner-1", created_at: "", updated_at: "", state: "bindings_set",
      basics: { pack_key: "p", version: "1.0.0", title: "P", default_domain: "payment" },
      bpmn: {
        process_id: "P", bpmn_file: "p.bpmn", sha256: "x", service_tasks: ["ApplyRepair"], user_tasks: ["ApproveRepair"],
        gateways: [], task_names: {},
        bindable_elements: [
          be({ element_id: "ApplyRepair", element_kind: "serviceTask", category: "capability", name: "Apply repair" }),
          be({ element_id: "ApproveRepair", element_kind: "userTask", category: "human", name: "Approve repair" }),
        ],
      },
      staged_artifacts: [{ artifact_key: "art.payment.in", version: "1.0.0", title: "in", json_schema: { type: "object", additionalProperties: false, properties: { envelope: {} } } }],
      reused_capability_refs: [], bindings: [],
      staged_capabilities: [{ capability_id: "cap.payment.apply_repair", version: "1.0.0", title: "Apply repair", side_effect: "side_effectful", input_name: "in", input_artifact_key: "art.payment.in", output_name: "out", output_artifact_key: "art.payment.out", endpoint: "http://x", tool: "apply_repair", transport: "streamable_http", headers: {} }],
      triage_rules: [], gateway_variables: [], sod_policies: [], roles: [],
      inferred: {
        roles: [], gateway_variables: [], capability_candidates: [{ source: "ApplyRepair", suggested_capability_id: "cap.payment.apply_repair", kind_hint: "mcp", needs_endpoint: true }],
        artifact_seeds: [], sod_candidates: [], annotations: [],
        bindings: [
          { element_id: "ApplyRepair", element_kind: "serviceTask", executor_type: "capability", suggested_capability_id: "cap.payment.apply_repair", suggested_role: "role.payment.ops_approver", suggested_hitl_mode: "none", source_lane: "L" },
          { element_id: "ApproveRepair", element_kind: "userTask", executor_type: "human", suggested_role: "role.payment.ops_approver", suggested_hitl_mode: "manual", source_lane: "L" },
        ],
      },
      dry_run_report: null, commit_progress: [], result_pack: null, last_cleared: [],
    };
    server.use(
      http.get(`${REG}/onboarding/sess-8`, () => HttpResponse.json(session)),
      http.get(`${REG}/capabilities`, () => HttpResponse.json([])),
      http.get(`${REG}/packs`, () => HttpResponse.json([])),
    );
    renderApp("/registry/onboard/sess-8", "owner-1");

    // the capability is pre-selected (an exact-id match) → a "suggested" chip renders (plus the ADR-048 D4
    // input-source chip for this entry task, derived off the bound capability → 2 chips)
    expect((await screen.findAllByText("suggested")).length).toBeGreaterThanOrEqual(2);
    expect(await screen.findByDisplayValue(/cap\.payment\.apply_repair@\^1\.0\.0/)).toBeInTheDocument();
    // side-effectful → the HITL floor bumped the pre-selected row from `none` to `approve_actions`
    expect(await screen.findByDisplayValue("approve_actions")).toBeInTheDocument();
    // the human task's executor role and HITL role both default to the SAME lane role
    expect(screen.getAllByDisplayValue("role.payment.ops_approver").length).toBeGreaterThanOrEqual(2);
  });

  it("bindings step authors the capability input_map with a graph-position suggestion (ADR-048)", async () => {
    const be = (over: Record<string, unknown>) => ({
      name: null, is_multi_instance: false, is_for_compensation: false,
      compensation_primary: null, in_event_subprocess: false, ...over,
    });
    const session = {
      session_id: "sess-9", created_by: "owner-1", created_at: "", updated_at: "", state: "bindings_set",
      basics: { pack_key: "p", version: "1.0.0", title: "P", default_domain: "payment" },
      // declared trigger (ADR-052) — its `exception_id` field name-matches the tool input so the per-field map is non-empty.
      trigger_artifact: { artifact_key: "art.payment.exc", version: "1.0.0", title: "t", json_schema: { type: "object", properties: { exception_id: {} } } },
      trigger_fields: { exception_id: "string" },
      bpmn: {
        process_id: "P", bpmn_file: "p.bpmn", sha256: "x", service_tasks: ["Enrich"], user_tasks: [],
        gateways: [], task_names: {},
        bindable_elements: [be({ element_id: "Enrich", element_kind: "serviceTask", category: "capability", name: "Enrich" })],
      },
      staged_artifacts: [{ artifact_key: "art.payment.enrich_input", version: "1.0.0", title: "in", json_schema: { type: "object", additionalProperties: false, properties: { exception_id: {} } } }],
      reused_capability_refs: [], bindings: [],
      staged_capabilities: [{ capability_id: "cap.payment.enrich", version: "1.0.0", title: "Enrich", side_effect: "read_only", input_name: "enrich_input", input_artifact_key: "art.payment.enrich_input", output_name: "enrich_output", output_artifact_key: "art.payment.enrich_output", endpoint: "http://x", tool: "enrich", transport: "streamable_http", headers: {} }],
      triage_rules: [], gateway_variables: [], sod_policies: [], roles: [],
      inferred: {
        roles: [], gateway_variables: [], artifact_seeds: [], sod_candidates: [], annotations: [],
        capability_candidates: [{ source: "Enrich", suggested_capability_id: "cap.payment.enrich", kind_hint: "mcp", needs_endpoint: true }],
        bindings: [{ element_id: "Enrich", element_kind: "serviceTask", executor_type: "capability", suggested_capability_id: "cap.payment.enrich", suggested_input_source: { enrich_input: { from: "trigger" } }, upstream_caps: [], suggested_hitl_mode: "none", source_lane: null }],
      },
      dry_run_report: null, commit_progress: [], result_pack: null, last_cleared: [],
    };
    server.use(
      http.get(`${REG}/onboarding/sess-9`, () => HttpResponse.json(session)),
      http.get(`${REG}/capabilities`, () => HttpResponse.json([])),
      http.get(`${REG}/packs`, () => HttpResponse.json([])),
    );
    renderApp("/registry/onboard/sess-9", "owner-1");

    // the input-source picker renders for the capability's input, pre-filled from the trigger suggestion
    expect(await screen.findByText(/Input source — where/)).toBeInTheDocument();
    expect(await screen.findByText(/enrich_input/)).toBeInTheDocument();
    expect(await screen.findByDisplayValue("from trigger")).toBeInTheDocument();
    // the pre-fill matches the inference → a "suggested" chip (there are 2: cap pre-select + input source)
    expect((await screen.findAllByText("suggested")).length).toBeGreaterThanOrEqual(2);
  });

  it("bindings step declares human-task outputs + offers them as an upstream source (ADR-050)", async () => {
    const be = (over: Record<string, unknown>) => ({
      name: null, is_multi_instance: false, is_for_compensation: false,
      compensation_primary: null, in_event_subprocess: false, ...over,
    });
    const orderSchema = { type: "object", properties: { order_type: { type: "string" } }, required: ["order_type"] };
    const session = {
      session_id: "sess-50", created_by: "owner-1", created_at: "", updated_at: "", state: "bindings_set",
      basics: { pack_key: "dinein", version: "1.0.0", title: "Dine-in", default_domain: "dining" },
      bpmn: {
        process_id: "P", bpmn_file: "p.bpmn", sha256: "x", service_tasks: ["Validate"], user_tasks: ["TakeOrder"],
        gateways: [], task_names: {},
        bindable_elements: [
          be({ element_id: "TakeOrder", element_kind: "userTask", category: "human", name: "Take order" }),
          be({ element_id: "Validate", element_kind: "serviceTask", category: "capability", name: "Validate order" }),
        ],
      },
      // art.dining.order is an operator-AUTHORED artifact (neither tool I/O nor trigger) → offered in the picker.
      authored_artifacts: [{ artifact_key: "art.dining.order", version: "1.0.0", title: "Order", json_schema: orderSchema }],
      staged_artifacts: [
        { artifact_key: "art.dining.validate_in", version: "1.0.0", title: "in", json_schema: { type: "object", properties: { order: {} } } },
        { artifact_key: "art.dining.validate_out", version: "1.0.0", title: "out", json_schema: { type: "object", properties: { ok: {} } } },
      ],
      reused_capability_refs: [],
      // TakeOrder already produces `order`; Validate sources its input from that human output.
      bindings: [
        { element_id: "TakeOrder", element_kind: "userTask", executor_type: "human", role: "role.dining.server",
          outputs: [{ name: "order", schema_ref: "art.dining.order@^1.0.0", required: true }] },
        { element_id: "Validate", element_kind: "serviceTask", executor_type: "capability",
          capability_ref: "cap.dining.validate@^1.0.0", hitl_mode: "none",
          input_sources: { validate_in: { from: "artifact", name: "order" } } },
      ],
      staged_capabilities: [{ capability_id: "cap.dining.validate", version: "1.0.0", title: "Validate", side_effect: "read_only", input_name: "validate_in", input_artifact_key: "art.dining.validate_in", output_name: "validate_out", output_artifact_key: "art.dining.validate_out", endpoint: "http://x", tool: "validate", transport: "streamable_http", headers: {} }],
      triage_rules: [], gateway_variables: [], sod_policies: [], roles: [],
      dry_run_report: null, commit_progress: [], result_pack: null, last_cleared: [], inferred: null,
    };
    server.use(
      http.get(`${REG}/onboarding/sess-50`, () => HttpResponse.json(session)),
      http.get(`${REG}/capabilities`, () => HttpResponse.json([])),
      http.get(`${REG}/packs`, () => HttpResponse.json([])),
    );
    renderApp("/registry/onboard/sess-50", "owner-1");

    // item 1: the human task shows an OUTPUTS section, pre-filled with its declared `order` output.
    expect(await screen.findByText(/Outputs — artifact\(s\) this task produces/)).toBeInTheDocument();
    expect(await screen.findByDisplayValue("order")).toBeInTheDocument();
    // the artifact-schema picker offers the authored art.dining.order.
    expect(await screen.findByRole("option", { name: "art.dining.order" })).toBeInTheDocument();
    // "author new artifact schema" is a first-class affordance in the same picker.
    expect(await screen.findByRole("option", { name: /Author new artifact schema/ })).toBeInTheDocument();
    // item 2: the capability's upstream-output source list offers the human output `order (TakeOrder)`.
    expect(await screen.findByRole("option", { name: "order (TakeOrder)" })).toBeInTheDocument();
  });

  it("bindings step shows an editable capability output name defaulted from the fed gateway (ADR-051)", async () => {
    const be = (over: Record<string, unknown>) => ({
      name: null, is_multi_instance: false, is_for_compensation: false,
      compensation_primary: null, in_event_subprocess: false, ...over,
    });
    const session = {
      session_id: "sess-51", created_by: "owner-1", created_at: "", updated_at: "", state: "bindings_set",
      basics: { pack_key: "dinein", version: "1.0.0", title: "D", default_domain: "dining" },
      bpmn: {
        process_id: "P", bpmn_file: "p.bpmn", sha256: "x", service_tasks: ["ValidateOrder"], user_tasks: [],
        gateways: ["Gateway_OrderOK"], task_names: {},
        // a second capability downstream so the upstream-output picker can offer ValidateOrder's chosen name
        bindable_elements: [
          be({ element_id: "ValidateOrder", element_kind: "serviceTask", category: "capability", name: "Validate order" }),
          be({ element_id: "Bill", element_kind: "serviceTask", category: "capability", name: "Generate bill" }),
        ],
      },
      staged_artifacts: [], reused_capability_refs: [], bindings: [],
      staged_capabilities: [
        { capability_id: "cap.dining.validate_order", version: "1.0.0", title: "Validate", side_effect: "read_only", input_name: "validate_order_input", input_artifact_key: "art.dining.validate_order_input", output_name: "validate_order_output", output_artifact_key: "art.dining.validate_order_output", endpoint: "http://x", tool: "validate_order", transport: "streamable_http", headers: {} },
        { capability_id: "cap.dining.generate_bill", version: "1.0.0", title: "Bill", side_effect: "read_only", input_name: "generate_bill_input", input_artifact_key: "art.dining.generate_bill_input", output_name: "generate_bill_output", output_artifact_key: "art.dining.generate_bill_output", endpoint: "http://x", tool: "generate_bill", transport: "streamable_http", headers: {} },
      ],
      triage_rules: [], gateway_variables: [], sod_policies: [], roles: [],
      inferred: {
        roles: [], gateway_variables: [{ gateway_id: "Gateway_OrderOK", variable: "validation.order_verdict" }],
        artifact_seeds: [], sod_candidates: [], annotations: [],
        capability_candidates: [
          { source: "ValidateOrder", suggested_capability_id: "cap.dining.validate_order", kind_hint: "mcp", needs_endpoint: true },
          { source: "Bill", suggested_capability_id: "cap.dining.generate_bill", kind_hint: "mcp", needs_endpoint: true },
        ],
        bindings: [
          { element_id: "ValidateOrder", element_kind: "serviceTask", executor_type: "capability", suggested_capability_id: "cap.dining.validate_order", suggested_input_source: { validate_order_input: { from: "trigger" } }, upstream_caps: [], upstream_producers: [], suggested_output_name: "validation", suggested_hitl_mode: "none", source_lane: null },
          { element_id: "Bill", element_kind: "serviceTask", executor_type: "capability", suggested_capability_id: "cap.dining.generate_bill", suggested_input_source: { generate_bill_input: { from: "artifact", element: "ValidateOrder" } }, upstream_caps: ["ValidateOrder"], upstream_producers: ["ValidateOrder"], suggested_hitl_mode: "none", source_lane: null },
        ],
      },
      dry_run_report: null, commit_progress: [], result_pack: null, last_cleared: [],
    };
    server.use(
      http.get(`${REG}/onboarding/sess-51`, () => HttpResponse.json(session)),
      http.get(`${REG}/capabilities`, () => HttpResponse.json([])),
      http.get(`${REG}/packs`, () => HttpResponse.json([])),
    );
    renderApp("/registry/onboard/sess-51", "owner-1");

    // the output-name field is pre-filled with the gateway-derived name (not validate_order_output)…
    expect(await screen.findByDisplayValue("validation")).toBeInTheDocument();
    // …carrying a "from gateway" provenance chip.
    expect(await screen.findByText("from gateway")).toBeInTheDocument();
    // and the downstream capability's upstream-output picker offers the CHOSEN name, not <tool>_output.
    expect(await screen.findByRole("option", { name: "validation (ValidateOrder)" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "validate_order_output (ValidateOrder)" })).not.toBeInTheDocument();
  });

  it("bindings step auto-fills an entry MCP task with a per-field composite, never whole-trigger (ADR-052)", async () => {
    const be = (over: Record<string, unknown>) => ({
      name: null, is_multi_instance: false, is_for_compensation: false,
      compensation_primary: null, in_event_subprocess: false, ...over,
    });
    const session = {
      session_id: "sess-of", created_by: "owner-1", created_at: "", updated_at: "", state: "bindings_set",
      basics: { pack_key: "dinein", version: "1.0.0", title: "D", default_domain: "dining" },
      // the DECLARED trigger (ADR-049/052) — its artifact gates the name-match; its fields drive it. Without the
      // artifact the fields would be the deployment's foreign samples (ignored).
      trigger_artifact: { artifact_key: "art.dining.order_ticket", version: "1.0.0", title: "t", json_schema: { type: "object", properties: { ticket_id: {}, order_type: {}, tender: {} } } },
      trigger_fields: { ticket_id: "string", order_type: "string", tender: "string" },
      bpmn: {
        process_id: "P", bpmn_file: "p.bpmn", sha256: "x", service_tasks: ["GetMenu"], user_tasks: [],
        gateways: [], task_names: {},
        bindable_elements: [be({ element_id: "GetMenu", element_kind: "serviceTask", category: "capability", name: "Present menu" })],
      },
      // the get_menu tool's CLOSED input schema — {request, ticket_id, tender}; only ticket_id + tender match the trigger.
      staged_artifacts: [{ artifact_key: "art.dining.get_menu_input", version: "1.0.0", title: "in", json_schema: { type: "object", additionalProperties: false, properties: { request: {}, ticket_id: {}, tender: {} } } }],
      reused_capability_refs: [], bindings: [],
      staged_capabilities: [{ capability_id: "cap.dining.get_menu", version: "1.0.0", title: "Menu", side_effect: "read_only", input_name: "get_menu_input", input_artifact_key: "art.dining.get_menu_input", output_name: "get_menu_output", output_artifact_key: "art.dining.get_menu_output", endpoint: "http://x", tool: "get_menu", transport: "streamable_http", headers: {} }],
      triage_rules: [], gateway_variables: [], sod_policies: [], roles: [],
      inferred: {
        roles: [], gateway_variables: [], artifact_seeds: [], sod_candidates: [], annotations: [],
        capability_candidates: [{ source: "GetMenu", suggested_capability_id: "cap.dining.get_menu", kind_hint: "mcp", needs_endpoint: true }],
        bindings: [{ element_id: "GetMenu", element_kind: "serviceTask", executor_type: "capability", suggested_capability_id: "cap.dining.get_menu", suggested_input_source: {}, upstream_caps: [], upstream_producers: [], suggested_hitl_mode: "none", source_lane: null }],
      },
      dry_run_report: null, commit_progress: [], result_pack: null, last_cleared: [],
    };
    server.use(
      http.get(`${REG}/onboarding/sess-of`, () => HttpResponse.json(session)),
      http.get(`${REG}/capabilities`, () => HttpResponse.json([])),
      http.get(`${REG}/packs`, () => HttpResponse.json([])),
    );
    renderApp("/registry/onboard/sess-of", "owner-1");

    // the entry task's input source is a COMPOSITE (never a whole {from:trigger} spread that would overflow
    // the closed tool schema); `ticket_id` + `tender` (declared trigger fields) are name-matched, and `request`
    // (not a trigger field) is left unmapped — NOT an empty {} map from the deployment's foreign samples.
    expect(await screen.findByText(/Input source — where/)).toBeInTheDocument();
    expect(await screen.findByDisplayValue("composite")).toBeInTheDocument();
    expect((await screen.findAllByDisplayValue("ticket_id")).length).toBeGreaterThanOrEqual(1);
    expect((await screen.findAllByDisplayValue("tender")).length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByDisplayValue("request")).not.toBeInTheDocument();   // non-trigger field → unmapped
  });

  it("bindings step auto-sources a capability input FIELD from a human output (ADR-052 E3)", async () => {
    const be = (over: Record<string, unknown>) => ({
      name: null, is_multi_instance: false, is_for_compensation: false,
      compensation_primary: null, in_event_subprocess: false, ...over,
    });
    const art = (key: string, props: Record<string, unknown>) =>
      ({ artifact_key: key, version: "1.0.0", title: key, json_schema: { type: "object", properties: props } });
    const session = {
      session_id: "sess-e3i", created_by: "owner-1", created_at: "", updated_at: "", state: "bindings_set",
      basics: { pack_key: "dinein", version: "1.0.0", title: "D", default_domain: "dining" },
      bpmn: {
        process_id: "P", bpmn_file: "p.bpmn", sha256: "x", service_tasks: ["ValidateOrder"], user_tasks: ["TakeOrder"],
        gateways: [], task_names: {},
        bindable_elements: [
          be({ element_id: "TakeOrder", element_kind: "userTask", category: "human", name: "Take order" }),
          be({ element_id: "ValidateOrder", element_kind: "serviceTask", category: "capability", name: "Validate order" }),
        ],
      },
      staged_artifacts: [
        art("art.dining.validate_order_input", { order: {}, table: {} }),
        art("art.dining.validate_order_output", { ok: {} }),
      ],
      authored_artifacts: [art("art.dining.order", { order_type: {} })],
      reused_capability_refs: [],
      // TakeOrder (human) produces `order`; ValidateOrder's input carries an `order` field.
      bindings: [
        { element_id: "TakeOrder", element_kind: "userTask", executor_type: "human", role: "role.dining.server",
          outputs: [{ name: "order", schema_ref: "art.dining.order@^1.0.0", required: true }] },
      ],
      staged_capabilities: [{ capability_id: "cap.dining.validate_order", version: "1.0.0", title: "Validate", side_effect: "read_only", input_name: "validate_order_input", input_artifact_key: "art.dining.validate_order_input", output_name: "validate_order_output", output_artifact_key: "art.dining.validate_order_output", endpoint: "http://x", tool: "validate_order", transport: "streamable_http", headers: {} }],
      triage_rules: [], gateway_variables: [], sod_policies: [], roles: [],
      inferred: {
        roles: [], gateway_variables: [], artifact_seeds: [], sod_candidates: [], annotations: [],
        capability_candidates: [{ source: "ValidateOrder", suggested_capability_id: "cap.dining.validate_order", kind_hint: "mcp", needs_endpoint: true }],
        bindings: [
          { element_id: "TakeOrder", element_kind: "userTask", executor_type: "human", suggested_role: "role.dining.server", suggested_hitl_mode: "manual", source_lane: null },
          { element_id: "ValidateOrder", element_kind: "serviceTask", executor_type: "capability", suggested_capability_id: "cap.dining.validate_order", suggested_input_source: {}, upstream_caps: [], upstream_producers: ["TakeOrder"], suggested_hitl_mode: "none", source_lane: null },
        ],
      },
      dry_run_report: null, commit_progress: [], result_pack: null, last_cleared: [],
    };
    server.use(
      http.get(`${REG}/onboarding/sess-e3i`, () => HttpResponse.json(session)),
      http.get(`${REG}/capabilities`, () => HttpResponse.json([])),
      http.get(`${REG}/packs`, () => HttpResponse.json([])),
    );
    renderApp("/registry/onboard/sess-e3i", "owner-1");

    // the capability's `order` input field auto-sources from the HUMAN output — `order (TakeOrder)` is selected.
    expect(await screen.findByRole("option", { name: "order (TakeOrder)", selected: true })).toBeInTheDocument();
  });

  it("policies step auto-derives the gateway source-artifact from the variable's output (ADR-052 E3)", async () => {
    const be = (id: string) => ({ element_id: id, element_kind: "serviceTask", category: "capability", name: id, is_multi_instance: false, is_for_compensation: false, compensation_primary: null, in_event_subprocess: false });
    const session = {
      session_id: "sess-e3g", created_by: "owner-1", created_at: "", updated_at: "", state: "policies_set",
      basics: { pack_key: "dinein", version: "1.0.0", title: "D", default_domain: "dining" },
      bpmn: {
        process_id: "P", bpmn_file: "p.bpmn", sha256: "x", service_tasks: ["ValidateOrder"], user_tasks: [],
        gateways: ["Gateway_OrderOK"], task_names: {}, bindable_elements: [be("ValidateOrder")],
      },
      staged_artifacts: [{ artifact_key: "art.dining.order_validation", version: "1.0.0", title: "v", json_schema: { type: "object", properties: { order_verdict: {} } } }],
      staged_capabilities: [], reused_capability_refs: [],
      bindings: [{ element_id: "ValidateOrder", element_kind: "serviceTask", executor_type: "capability", capability_ref: "cap.dining.validate_order@^1.0.0", hitl_mode: "none", outputs: [{ name: "validation", schema_ref: "art.dining.order_validation@^1.0.0", required: true }] }],
      triage_rules: [], gateway_variables: [], sod_policies: [], roles: [],
      inferred: {
        roles: [], bindings: [], capability_candidates: [], artifact_seeds: [], annotations: [], sod_candidates: [],
        gateway_variables: [{ gateway_id: "Gateway_OrderOK", variable: "validation.order_verdict" }],
      },
      dry_run_report: null, commit_progress: [], result_pack: null, last_cleared: [],
    };
    server.use(
      http.get(`${REG}/onboarding/sess-e3g`, () => HttpResponse.json(session)),
      http.get(`${REG}/capabilities`, () => HttpResponse.json([])),
    );
    renderApp("/registry/onboard/sess-e3g", "owner-1");

    // the decision variable pre-fills from the condition, and its source artifact auto-derives from `validation`.
    expect(await screen.findByDisplayValue("validation.order_verdict")).toBeInTheDocument();
    expect(await screen.findByDisplayValue("art.dining.order_validation")).toBeInTheDocument();
  });

  it("bindings step derives the input_map off the BOUND capability even when the element name diverges (ADR-048 D4)", async () => {
    const be = (over: Record<string, unknown>) => ({
      name: null, is_multi_instance: false, is_for_compensation: false,
      compensation_primary: null, in_event_subprocess: false, ...over,
    });
    // element name "Investigate" does NOT token-match the tool id "enrich_investigation" (the fuzzy pre-select
    // would fail) — but a binding already binds the capability, so the source suggestion must still resolve.
    const session = {
      session_id: "sess-div", created_by: "owner-1", created_at: "", updated_at: "", state: "bindings_set",
      basics: { pack_key: "p", version: "1.0.0", title: "P", default_domain: "payment" },
      // declared trigger (ADR-052) so the tool's `exception_id` input field name-matches → non-empty per-field map.
      trigger_artifact: { artifact_key: "art.payment.exc", version: "1.0.0", title: "t", json_schema: { type: "object", properties: { exception_id: {} } } },
      trigger_fields: { exception_id: "string" },
      bpmn: {
        process_id: "P", bpmn_file: "p.bpmn", sha256: "x", service_tasks: ["Investigate"], user_tasks: [],
        gateways: [], task_names: {},
        bindable_elements: [be({ element_id: "Investigate", element_kind: "serviceTask", category: "capability", name: "Investigate" })],
      },
      staged_artifacts: [{ artifact_key: "art.payment.enrich_investigation_input", version: "1.0.0", title: "in", json_schema: { type: "object", additionalProperties: false, properties: { exception_id: {} } } }],
      reused_capability_refs: [],
      bindings: [{ element_id: "Investigate", element_kind: "serviceTask", executor_type: "capability", capability_ref: "cap.payment.enrich_investigation@^1.0.0", hitl_mode: "none", input_sources: {} }],
      staged_capabilities: [{ capability_id: "cap.payment.enrich_investigation", version: "1.0.0", title: "Enrich", side_effect: "read_only", input_name: "enrich_investigation_input", input_artifact_key: "art.payment.enrich_investigation_input", output_name: "enrich_investigation_output", output_artifact_key: "art.payment.enrich_investigation_output", endpoint: "http://x", tool: "enrich_investigation", transport: "streamable_http", headers: {} }],
      triage_rules: [], gateway_variables: [], sod_policies: [], roles: [],
      inferred: {
        roles: [], gateway_variables: [], artifact_seeds: [], sod_candidates: [], annotations: [], capability_candidates: [],
        bindings: [{ element_id: "Investigate", element_kind: "serviceTask", executor_type: "capability", suggested_capability_id: "cap.payment.investigate", suggested_input_source: { from: "trigger" }, upstream_caps: [], suggested_hitl_mode: "none", source_lane: null }],
      },
      dry_run_report: null, commit_progress: [], result_pack: null, last_cleared: [],
    };
    server.use(
      http.get(`${REG}/onboarding/sess-div`, () => HttpResponse.json(session)),
      http.get(`${REG}/capabilities`, () => HttpResponse.json([])),
      http.get(`${REG}/packs`, () => HttpResponse.json([])),
    );
    renderApp("/registry/onboard/sess-div", "owner-1");

    // resolved off the bound capability_ref (not the failed name match) → the entry input sources the trigger
    expect(await screen.findByText(/enrich_investigation_input/)).toBeInTheDocument();
    expect(await screen.findByDisplayValue("from trigger")).toBeInTheDocument();
    expect((await screen.findAllByText("suggested")).length).toBeGreaterThanOrEqual(1);
  });

  it("bindings step best-guesses a divergent-name capability instead of a cold Select… (batch-4)", async () => {
    const be = (over: Record<string, unknown>) => ({
      name: null, is_multi_instance: false, is_for_compensation: false,
      compensation_primary: null, in_event_subprocess: false, ...over,
    });
    // "Enrich" only weakly matches the tool id "enrich_investigation" (below the auto bar) — the old Jaccard
    // left it "Select…". The ranked scorer now pre-fills it as a one-click "likely" best guess.
    const session = {
      session_id: "sess-lk", created_by: "owner-1", created_at: "", updated_at: "", state: "bindings_set",
      basics: { pack_key: "p", version: "1.0.0", title: "P", default_domain: "payment" },
      bpmn: {
        process_id: "P", bpmn_file: "p.bpmn", sha256: "x", service_tasks: ["Enrich"], user_tasks: [],
        gateways: [], task_names: {},
        bindable_elements: [be({ element_id: "Enrich", element_kind: "serviceTask", category: "capability", name: "Enrich" })],
      },
      staged_artifacts: [], reused_capability_refs: [], bindings: [],
      staged_capabilities: [{ capability_id: "cap.payment.enrich_investigation", version: "1.0.0", title: "Enrich", side_effect: "read_only", input_name: "enrich_investigation_input", input_artifact_key: "art.payment.enrich_investigation_input", output_name: "enrich_investigation_output", output_artifact_key: "art.payment.enrich_investigation_output", endpoint: "http://x", tool: "enrich_investigation", transport: "streamable_http", headers: {} }],
      triage_rules: [], gateway_variables: [], sod_policies: [], roles: [],
      inferred: {
        roles: [], gateway_variables: [], artifact_seeds: [], sod_candidates: [], annotations: [], capability_candidates: [],
        bindings: [{ element_id: "Enrich", element_kind: "serviceTask", executor_type: "capability", suggested_capability_id: "cap.payment.enrich", suggested_input_source: { from: "trigger" }, upstream_caps: [], suggested_hitl_mode: "none", source_lane: null }],
      },
      dry_run_report: null, commit_progress: [], result_pack: null, last_cleared: [],
    };
    server.use(
      http.get(`${REG}/onboarding/sess-lk`, () => HttpResponse.json(session)),
      http.get(`${REG}/capabilities`, () => HttpResponse.json([])),
      http.get(`${REG}/packs`, () => HttpResponse.json([])),
    );
    renderApp("/registry/onboard/sess-lk", "owner-1");

    // pre-filled with the best-guess capability (not a cold Select…) + a dim "likely" chip
    expect(await screen.findByDisplayValue(/cap\.payment\.enrich_investigation@\^1\.0\.0/)).toBeInTheDocument();
    expect(await screen.findByText("likely")).toBeInTheDocument();
  });

  it("capabilities step reuses a capability via on-demand search (no eager catalog load) (batch-1)", async () => {
    let eagerLoads = 0;
    const session = {
      session_id: "sess-7", created_by: "owner-1", created_at: "", updated_at: "", state: "capabilities_resolved",
      basics: { pack_key: "p", version: "1.0.0", title: "P", default_domain: "payment" },
      bpmn: { process_id: "P", bpmn_file: "p.bpmn", sha256: "x", service_tasks: [], user_tasks: [], gateways: [], task_names: {}, bindable_elements: [], message_flows: [] },
      staged_artifacts: [], staged_capabilities: [], reused_capability_refs: [], bindings: [],
      triage_rules: [], gateway_variables: [], sod_policies: [], roles: [],
      inferred: { roles: [], bindings: [], gateway_variables: [], capability_candidates: [], artifact_seeds: [], sod_candidates: [], annotations: [] },
      dry_run_report: null, commit_progress: [], result_pack: null, last_cleared: [],
    };
    server.use(
      http.get(`${REG}/onboarding/sess-7`, () => HttpResponse.json(session)),
      http.get(`${REG}/capabilities`, ({ request }) => {
        const q = new URL(request.url).searchParams.get("q");
        if (!q) { eagerLoads++; return HttpResponse.json([]); }   // an eager (no-q) load — must NOT happen
        return HttpResponse.json("cap.payment.screen".includes(q.toLowerCase())
          ? [{ capability_id: "cap.payment.screen", version: "1.0.0", kind: "mcp", side_effect: "read_only" }] : []);
      }),
    );
    const user = userEvent.setup();
    renderApp("/registry/onboard/sess-7", "owner-1");

    // the reuse card is a button, not a pre-loaded list
    const openBtn = await screen.findByRole("button", { name: /Reuse a capability/i });
    await user.click(openBtn);
    await user.type(await screen.findByPlaceholderText(/search the active catalog/i), "screen");
    // on-demand result appears; selecting it adds a removable chip
    const result = await screen.findByText("cap.payment.screen@^1.0.0");
    await user.click(result);
    expect(screen.getAllByText("cap.payment.screen@^1.0.0").length).toBeGreaterThanOrEqual(2); // dialog + chip
    expect(eagerLoads).toBe(0);   // the step never eager-loaded the whole catalog
  });

  it("triage step authors against the trigger schema — field picker + type-valid ops (batch-4)", async () => {
    const session = {
      session_id: "sess-tr", created_by: "owner-1", created_at: "", updated_at: "", state: "triage_set",
      basics: { pack_key: "p", version: "1.0.0", title: "P", default_domain: "payment" },
      trigger_fields: { reason_codes: "array", exception_type: "string" },
      bpmn: { process_id: "P", bpmn_file: "p.bpmn", sha256: "x", service_tasks: [], user_tasks: [], gateways: [], task_names: {}, bindable_elements: [], message_flows: [] },
      staged_artifacts: [], staged_capabilities: [], reused_capability_refs: [], bindings: [],
      triage_rules: [], gateway_variables: [], sod_policies: [], roles: [],
      inferred: { roles: [], bindings: [], gateway_variables: [], capability_candidates: [], artifact_seeds: [], sod_candidates: [], annotations: [] },
      dry_run_report: null, commit_progress: [], result_pack: null, last_cleared: [],
    };
    server.use(http.get(`${REG}/onboarding/sess-tr`, () => HttpResponse.json(session)));
    renderApp("/registry/onboard/sess-tr", "owner-1");

    // the leaf field is a picker of the schema paths (typed), defaulting to the first (array) field with a
    // type-valid op — the "eq" that a scalar mindset would pick is NOT offered for the array field.
    expect(await screen.findByRole("option", { name: /reason_codes · array/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /exception_type · string/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "intersects" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "eq" })).not.toBeInTheDocument();   // invalid on an array
  });

  it("capabilities step surfaces a hard id-collision with a diff and the two fixes (batch-4)", async () => {
    const session = {
      session_id: "sess-col", created_by: "owner-1", created_at: "", updated_at: "", state: "capabilities_resolved",
      basics: { pack_key: "ws_stan", version: "1.0.0", title: "P", default_domain: "payment" },
      bpmn: { process_id: "P", bpmn_file: "p.bpmn", sha256: "x", service_tasks: [], user_tasks: [], gateways: [], task_names: {}, bindable_elements: [], message_flows: [] },
      staged_artifacts: [], staged_capabilities: [], reused_capability_refs: [], bindings: [],
      triage_rules: [], gateway_variables: [], sod_policies: [], roles: [],
      inferred: { roles: [], bindings: [], gateway_variables: [], capability_candidates: [], artifact_seeds: [], sod_candidates: [], annotations: [] },
      dry_run_report: null, commit_progress: [], result_pack: null, last_cleared: [],
    };
    server.use(
      http.get(`${REG}/onboarding/sess-col`, () => HttpResponse.json(session)),
      http.get(`${REG}/capabilities`, () => HttpResponse.json([])),
      http.post(`${REG}/capabilities/introspect-mcp`, () => HttpResponse.json({
        endpoint: "http://mcp:8060/mcp", transport: "streamable_http",
        tools: [{
          name: "screen_party", description: "Screen a party.", compliance: { compliant: true, reasons: [] },
          input_schema: { type: "object", properties: { party: { type: "string" } } },
          output_schema: { type: "object", properties: { hit: { type: "boolean" } } },
          suggested_input_artifact_key: "art.payment.screen_party_input",
          suggested_output_artifact_key: "art.payment.screen_party_output",
          suggested_capability_id: "cap.payment.screen_party",
          id_collision: {
            capability_id: "cap.payment.screen_party", severity: "hard", active_version: "1.0.0",
            active_kind: "skill",
            diff: "active: kind=skill, in=[], out=[]; introspected: kind=mcp, in=['art.payment.screen_party_input'], out=['art.payment.screen_party_output']",
          },
        }],
      })),
    );
    const user = userEvent.setup();
    renderApp("/registry/onboard/sess-col", "owner-1");

    await user.type(await screen.findByPlaceholderText(/your-mcp-service/i), "http://mcp:8060/mcp");
    await user.click(await screen.findByRole("button", { name: /Introspect/i }));

    // the hard collision is surfaced with its contract diff and both one-click fixes
    expect(await screen.findByText(/Id collision/i)).toBeInTheDocument();
    expect(screen.getByText(/kind=skill/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Use a distinct domain/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Reuse the existing capability/i })).toBeInTheDocument();
  });

  it("capabilities step surfaces an opaque-object warning without blocking selection (ADR-057)", async () => {
    const session = {
      session_id: "sess-warn", created_by: "owner-1", created_at: "", updated_at: "", state: "capabilities_resolved",
      basics: { pack_key: "ws_stan", version: "1.0.0", title: "P", default_domain: "payment" },
      bpmn: { process_id: "P", bpmn_file: "p.bpmn", sha256: "x", service_tasks: [], user_tasks: [], gateways: [], task_names: {}, bindable_elements: [], message_flows: [] },
      staged_artifacts: [], staged_capabilities: [], reused_capability_refs: [], bindings: [],
      triage_rules: [], gateway_variables: [], sod_policies: [], roles: [],
      inferred: { roles: [], bindings: [], gateway_variables: [], capability_candidates: [], artifact_seeds: [], sod_candidates: [], annotations: [] },
      dry_run_report: null, commit_progress: [], result_pack: null, last_cleared: [],
    };
    server.use(
      http.get(`${REG}/onboarding/sess-warn`, () => HttpResponse.json(session)),
      http.get(`${REG}/capabilities`, () => HttpResponse.json([])),
      http.post(`${REG}/capabilities/introspect-mcp`, () => HttpResponse.json({
        endpoint: "http://mcp:8060/mcp", transport: "streamable_http",
        tools: [{
          name: "apply_repair", description: "Apply a repair.",
          // compliant, but with a non-blocking advisory
          compliance: {
            compliant: true, reasons: [],
            warnings: ["apply_repair.repair is an untyped object — its HITL form will be a raw editor unless the schema declares its properties"],
          },
          input_schema: { type: "object", properties: { repair: { type: "object" } } },
          output_schema: { type: "object", properties: { acknowledged: { type: "boolean" } } },
          suggested_input_artifact_key: "art.payment.apply_repair_input",
          suggested_output_artifact_key: "art.payment.apply_repair_output",
          suggested_capability_id: "cap.payment.apply_repair",
        }],
      })),
    );
    const user = userEvent.setup();
    renderApp("/registry/onboard/sess-warn", "owner-1");

    await user.type(await screen.findByPlaceholderText(/your-mcp-service/i), "http://mcp:8060/mcp");
    await user.click(await screen.findByRole("button", { name: /Introspect/i }));

    // the advisory renders...
    expect(await screen.findByText(/apply_repair\.repair is an untyped object/i)).toBeInTheDocument();
    // ...and the tool is still compliant + selectable (warning never blocks)
    expect(screen.getByText("compliant")).toBeInTheDocument();
    const checkbox = screen.getAllByRole("checkbox").find((c) => !(c as HTMLInputElement).disabled);
    expect(checkbox).toBeDefined();
  });
});

describe("Pack config editing (ADR-056)", () => {
  const active = { ...synthPack, version: "1.1.0", status: "active", updated_at: "2026-08-01T00:00:00Z" };
  const deprecated = { ...synthPack, version: "1.0.0", status: "deprecated", updated_at: "2026-07-01T00:00:00Z" };

  function stubDetail() {
    server.use(
      http.get(`${REG}/packs/test-pack/1.1.0`, () => HttpResponse.json(active)),
      http.get(`${REG}/packs/test-pack/1.1.0/bpmn`, () => HttpResponse.text("<x/>")),
      http.get(`${REG}/packs/test-pack/1.1.0/resolution`, () => HttpResponse.json({ capabilities: {}, artifacts: {} })),
      http.get(`${REG}/packs/test-pack`, () => HttpResponse.json([deprecated, active])),
    );
  }

  it("an active pack shows Edit and opens the edit session in the stepped review", async () => {
    let editBody: Record<string, unknown> | undefined;
    stubDetail();
    server.use(http.post(`${REG}/onboarding/from-pack/test-pack`, async ({ request }) => {
      editBody = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({ session_id: "onb-edit" });
    }));
    const user = userEvent.setup();
    renderApp("/registry/packs/test-pack/1.1.0", "owner-1");

    await user.click(await screen.findByRole("button", { name: /edit config/i }));
    await waitFor(() => expect(editBody).toBeDefined());
    expect(editBody!.bump).toBe("minor");                       // default bump; a major option is selectable
  });

  it("the versions tab lists history and Make live calls rollback", async () => {
    let rolledTo: string | undefined;
    stubDetail();
    server.use(http.post(`${REG}/packs/test-pack/rollback`, async ({ request }) => {
      rolledTo = ((await request.json()) as { to_version: string }).to_version;
      return HttpResponse.json({ ...deprecated, status: "active" });
    }));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    renderApp("/registry/packs/test-pack/1.1.0", "owner-1");

    await user.click(await screen.findByRole("tab", { name: /versions/i }));
    expect(await screen.findByText("1.0.0")).toBeInTheDocument();   // history renders both versions
    await user.click(screen.getByRole("button", { name: /make live/i }));   // rollback the deprecated one
    await waitFor(() => expect(rolledTo).toBe("1.0.0"));
  });
});
