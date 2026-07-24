import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { screen } from "@testing-library/react";
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
      staged_artifacts: [], reused_capability_refs: [], bindings: [],
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
      bpmn: {
        process_id: "P", bpmn_file: "p.bpmn", sha256: "x", service_tasks: ["Enrich"], user_tasks: [],
        gateways: [], task_names: {},
        bindable_elements: [be({ element_id: "Enrich", element_kind: "serviceTask", category: "capability", name: "Enrich" })],
      },
      staged_artifacts: [], reused_capability_refs: [], bindings: [],
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
      bpmn: {
        process_id: "P", bpmn_file: "p.bpmn", sha256: "x", service_tasks: ["Investigate"], user_tasks: [],
        gateways: [], task_names: {},
        bindable_elements: [be({ element_id: "Investigate", element_kind: "serviceTask", category: "capability", name: "Investigate" })],
      },
      staged_artifacts: [], reused_capability_refs: [],
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
});
