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
      bpmn: { process_id: "proc", bpmn_file: "p.bpmn", sha256: "x", service_tasks: ["T"], user_tasks: [], gateways: [], task_names: {} },
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
        service_tasks: ["T"], user_tasks: [], gateways: [], task_names: {},
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
  });
});
