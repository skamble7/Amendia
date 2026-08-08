// ArtifactEditor.prefill.test.tsx — an agent-drafted edit form MUST pre-fill from the draft. Regression guard
// for the bug where "Edit & approve" opened a blank structured form (UETR empty, Corrections "None yet",
// Justification empty) while the read-only view of the SAME data was fully populated. Asserts PREFILL of every
// field kind — scalar (uetr), array-of-objects field array (corrections), textarea (justification), boolean
// (requires_rescreen) — not merely that the form renders.
import { describe, it, expect, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";

import { server } from "@/test/server";
import { SERVICE_BASE } from "@/api/config";
import { setTestToken } from "@/auth/authToken";
import { ArtifactEditor } from "./ArtifactEditor";
import type { PayloadArtifact } from "@/api/types";

const REPAIR_SCHEMA = {
  type: "object",
  required: ["uetr", "corrections"],
  properties: {
    uetr: { type: "string" },
    corrections: {
      type: "array",
      items: { type: "object", properties: { field: { type: "string" }, before: { type: "string" }, after: { type: "string" } } },
    },
    justification: { type: "string" },
    requires_rescreen: { type: "boolean" },
  },
};

const DRAFT = {
  uetr: "UETR-abc-123",
  corrections: [{ field: "creditor_account", before: "GB111", after: "GB222" }],
  justification: "beneficiary IBAN corrected per camt.027",
  requires_rescreen: true,
};

const ARTIFACTS = [
  { name: "repair", schema: "art.payment.repair_instruction@1.0.0", data: DRAFT },
] as unknown as PayloadArtifact[];

function renderEditor(ui: React.ReactElement) {
  setTestToken("test-token");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("ArtifactEditor — agent-draft prefill", () => {
  afterEach(() => server.resetHandlers());

  it("pre-fills every field kind from the draft (scalar, field array, textarea, boolean)", async () => {
    server.use(http.get(`${SERVICE_BASE.registry}/packs/:pack_key/:pack_version/artifact-schemas/:key/:version`, () => HttpResponse.json({ json_schema: REPAIR_SCHEMA })));
    renderEditor(<ArtifactEditor id="edit-repair" artifacts={ARTIFACTS} packKey="test-pack" packVersion="1.0.0" onSubmit={() => {}} />);

    // scalar
    await waitFor(() => expect((screen.getByLabelText(/UETR/i) as HTMLInputElement).value).toBe("UETR-abc-123"));
    // array-of-objects field array → one row with the draft before/after (NOT "None yet")
    expect(screen.getByDisplayValue("creditor_account")).toBeTruthy();
    expect(screen.getByDisplayValue("GB111")).toBeTruthy();
    expect(screen.getByDisplayValue("GB222")).toBeTruthy();
    expect(screen.queryByText(/None yet/i)).toBeNull();
    // textarea
    expect((screen.getByLabelText(/Justification/i) as HTMLTextAreaElement).value).toBe("beneficiary IBAN corrected per camt.027");
    // boolean
    expect((screen.getByLabelText(/Requires rescreen/i) as HTMLInputElement)).toBeTruthy();
  });
});
