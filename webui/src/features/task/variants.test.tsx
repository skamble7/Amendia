// variants.test.tsx — ManualVariant copy must match whether the gate has an editable output. A gate with an
// editable artifact (e.g. Task_ObtainInfo) is authoring work ("complete or correct it" + "Complete task"); a
// gate with none (e.g. Task_ApproveRepair — an input to approve, no output) is an approve/escalate gate, so
// the "correct it" copy would mislead ("Review … approve" + "Approve").
import { describe, it, expect, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";

import { server } from "@/test/server";
import { SERVICE_BASE } from "@/api/config";
import { setTestToken } from "@/auth/authToken";
import { synthTask } from "@/test/fixtures";
import { ManualVariant } from "./variants";
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

describe("ManualVariant — copy matches editability", () => {
  afterEach(() => server.resetHandlers());

  it("no editable output → approval copy + 'Approve'", () => {
    server.use(http.get(`${SERVICE_BASE.registry}/artifact-schemas/:key/:version`, () => HttpResponse.json({ json_schema: {} })));
    renderVariant(
      <ManualVariant task={manualTask([{ name: "repair", schema: "art.payment.repair@1.0.0", data: { field: "x" } }])} onDecide={() => {}} pending={false} />,
    );
    expect(screen.getByText(/Review the drafted output and approve, or escalate/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Approve" })).toBeTruthy();
    expect(screen.queryByText(/complete or correct it/i)).toBeNull();
    expect(screen.queryByRole("button", { name: "Complete task" })).toBeNull();
  });

  it("editable output → authoring copy + 'Complete task'", () => {
    server.use(http.get(`${SERVICE_BASE.registry}/artifact-schemas/:key/:version`, () => HttpResponse.json({ json_schema: {} })));
    renderVariant(
      <ManualVariant task={manualTask([{ name: "rfi", schema: "art.payment.rfi@1.0.0", data: {}, draft: true }])} onDecide={() => {}} pending={false} />,
    );
    expect(screen.getByText(/complete or correct it/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Complete task" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });
});
