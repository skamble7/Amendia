import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { screen } from "@testing-library/react";
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
});
