// variants.test.tsx — ManualVariant copy must match whether the gate has an editable output. A gate with an
// editable artifact (e.g. Task_ObtainInfo) is authoring work ("complete or correct it" + "Complete task"); a
// gate with none (e.g. Task_ApproveRepair — an input to approve, no output) is an approve/escalate gate, so
// the "correct it" copy would mislead ("Review … approve" + "Approve").
import { describe, it, expect, afterEach, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { server } from "@/test/server";
import { SERVICE_BASE } from "@/api/config";
import { setTestToken } from "@/auth/authToken";
import { synthTask } from "@/test/fixtures";
import { ManualVariant, ReviewVariant } from "./variants";
import type { HitlTask, PayloadArtifact } from "@/api/types";

function renderVariant(ui: React.ReactElement) {
  setTestToken("test-token");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

function manualTask(artifacts: unknown[]): HitlTask {
  return synthTask({
    hitl_mode: "manual",
    payload: { artifacts: artifacts as PayloadArtifact[], proposed_actions: null, context_url: "/x" },
  });
}

describe("ManualVariant — copy matches draft presence", () => {
  afterEach(() => server.resetHandlers());
  const schemaOk = () =>
    server.use(http.get(`${SERVICE_BASE.registry}/packs/:pack_key/:pack_version/artifact-schemas/:key/:version`, () => HttpResponse.json({ json_schema: {} })));

  it("(c) no editable output → approve-only copy + 'Approve'", () => {
    schemaOk();
    renderVariant(
      <ManualVariant task={manualTask([{ name: "repair", schema: "art.payment.repair@1.0.0", data: { field: "x" } }])} onDecide={() => {}} pending={false} />,
    );
    expect(screen.getByText(/Review the drafted output and approve, or escalate/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Approve" })).toBeTruthy();
    expect(screen.queryByText(/complete or correct it/i)).toBeNull();
    expect(screen.queryByRole("button", { name: "Complete task" })).toBeNull();
  });

  it("(a) editable output WITH an agent pre-draft → 'complete or correct it' + 'Complete task'", () => {
    schemaOk();
    renderVariant(
      <ManualVariant task={manualTask([{ name: "rfi", schema: "art.payment.rfi@1.0.0", data: { question: "Confirm IBAN" }, draft: true }])} onDecide={() => {}} pending={false} />,
    );
    expect(screen.getByText(/pre-drafted it — complete or correct it/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Complete task" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });

  it("(b) editable output with NO pre-draft → 'provide the required output' (not the misleading pre-draft copy)", () => {
    schemaOk();
    renderVariant(
      <ManualVariant
        task={manualTask([{ name: "approved_repair", schema: "art.payment.approved_repair@1.0.0", data: {}, draft: true, authored_by_human: true }])}
        onDecide={() => {}}
        pending={false}
      />,
    );
    expect(screen.getByText(/Provide the required output/i)).toBeTruthy();
    expect(screen.queryByText(/complete or correct it/i)).toBeNull();       // the empty human-authored output isn't "pre-drafted"
    expect(screen.getByRole("button", { name: "Complete task" })).toBeTruthy();
  });
});

const REPAIR_SCHEMA = {
  type: "object",
  required: ["uetr"],
  properties: { uetr: { type: "string" }, justification: { type: "string" } },
};
const REPAIR_DRAFT = { uetr: "UETR-abc-123", justification: "IBAN corrected" };

function reviewTask(): HitlTask {
  return synthTask({
    hitl_mode: "review_after",
    payload: {
      artifacts: [{ name: "repair", schema: "art.payment.repair_instruction@1.0.0", data: REPAIR_DRAFT }] as PayloadArtifact[],
      proposed_actions: null,
      context_url: "/x",
    },
  });
}

describe("ReviewVariant — Edit & approve must not implicitly submit", () => {
  afterEach(() => server.resetHandlers());

  it("clicking 'Edit & approve' reveals the prefilled form and records NO decision; only 'Save edits & approve' submits", async () => {
    server.use(http.get(`${SERVICE_BASE.registry}/packs/:pack_key/:pack_version/artifact-schemas/:key/:version`, () => HttpResponse.json({ json_schema: REPAIR_SCHEMA })));
    const onDecide = vi.fn();
    const user = userEvent.setup();
    renderVariant(<ReviewVariant task={reviewTask()} onDecide={onDecide} pending={false} />);

    // enter edit mode — this mounts the ArtifactEditor <form>; the button must NOT submit it
    await user.click(await screen.findByRole("button", { name: /Edit & approve/i }));

    // the prefilled editable form appears…
    expect(await screen.findByDisplayValue("UETR-abc-123")).toBeTruthy();
    // …and NO decision was recorded by merely opening the editor
    expect(onDecide).not.toHaveBeenCalled();

    // only the explicit submitter records the decision
    await user.click(screen.getByRole("button", { name: /Save edits & approve/i }));
    await waitFor(() => expect(onDecide).toHaveBeenCalledTimes(1));
    expect(onDecide.mock.calls[0]![0].decision).toBe("edit_and_approve");
    expect((onDecide.mock.calls[0]![0].edits as Record<string, unknown>).repair).toMatchObject({ uetr: "UETR-abc-123" });
  });
});
