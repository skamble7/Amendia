// ArtifactEditor.test.tsx — Part B tabs: a multi-artifact gate (e.g. Task_ObtainInfo's read-only dossier +
// editable rfi + editable info_resolution) renders a tab per artifact, and "Complete" submits edits keyed by
// artifact NAME (the backend's edits.get(spec.name) contract) — not just artifacts[0].
import { describe, it, expect, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { server } from "@/test/server";
import { SERVICE_BASE } from "@/api/config";
import { setTestToken } from "@/auth/authToken";
import { ArtifactEditor } from "./ArtifactEditor";
import type { PayloadArtifact } from "@/api/types";

const REG = SERVICE_BASE.registry;

const RFI_SCHEMA = {
  type: "object",
  required: ["channel", "questions"],
  properties: { channel: { enum: ["camt.027", "email"] }, questions: { type: "array", items: { type: "string" } } },
};
const RES_SCHEMA = {
  type: "object",
  required: ["outcome"],
  properties: { outcome: { enum: ["resolved", "cannot_obtain"] }, details: { type: "string" } },
};

function schemaHandler() {
  return http.get(`${REG}/artifact-schemas/:key/:version`, ({ params }) => {
    const key = String(params.key);
    const json_schema = key.includes("rfi_request")
      ? RFI_SCHEMA
      : key.includes("info_resolution")
        ? RES_SCHEMA
        : { type: "object", properties: { summary: { type: "string" } } };
    return HttpResponse.json({ json_schema });
  });
}

function renderEditor(ui: React.ReactElement) {
  setTestToken("test-token");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const ARTIFACTS = [
  { name: "dossier", schema: "art.payment.enrich@1.0.0", data: { summary: "context" } },
  { name: "rfi", schema: "art.payment.rfi_request@1.0.0", data: { channel: "camt.027", questions: ["Confirm the beneficiary IBAN"] }, draft: true },
  { name: "info_resolution", schema: "art.payment.info_resolution@1.0.0", data: {}, draft: true, authored_by_human: true },
] as unknown as PayloadArtifact[];

describe("ArtifactEditor — multi-artifact tabs (Part B)", () => {
  afterEach(() => server.resetHandlers());

  it("renders a tab per artifact and submits edits keyed by artifact name", async () => {
    server.use(schemaHandler());
    const user = userEvent.setup();
    let submitted: Record<string, unknown> | undefined;

    renderEditor(
      <>
        <ArtifactEditor id="ed" artifacts={ARTIFACTS} isEditable={(a) => Boolean((a as Record<string, unknown>).draft)} onSubmit={(e) => (submitted = e)} />
        <button type="submit" form="ed">go</button>
      </>,
    );

    // a tab per artifact — not just the first (the form mounts once its schemas settle)
    expect(await screen.findByRole("tab", { name: /Dossier/i })).toBeTruthy();
    expect(screen.getByRole("tab", { name: /RFI/i })).toBeTruthy();
    expect(screen.getByRole("tab", { name: /Info resolution/i })).toBeTruthy();

    // rfi tab: once its schema resolves, the editable array renders as a structured input (not raw JSON)
    await user.click(screen.getByRole("tab", { name: /RFI/i }));
    await waitFor(() => expect(screen.getByDisplayValue("Confirm the beneficiary IBAN")).toBeTruthy());

    // info_resolution tab: author the required outcome (human-only artifact, no agent draft)
    await user.click(screen.getByRole("tab", { name: /Info resolution/i }));
    await user.selectOptions(screen.getByLabelText(/Outcome/i), "resolved");

    await user.click(screen.getByText("go"));

    await waitFor(() => expect(submitted).toBeDefined());
    // edits keyed by artifact name — the read-only dossier is NOT included
    expect(Object.keys(submitted!).sort()).toEqual(["info_resolution", "rfi"]);
    expect((submitted!.rfi as Record<string, unknown>).channel).toBe("camt.027");
    expect((submitted!.rfi as Record<string, unknown>).questions).toEqual(["Confirm the beneficiary IBAN"]);
    expect((submitted!.info_resolution as Record<string, unknown>).outcome).toBe("resolved");
  });

  it("offers a per-artifact Raw JSON escape hatch that submits the edited blob", async () => {
    server.use(schemaHandler());
    const user = userEvent.setup();
    let submitted: Record<string, unknown> | undefined;
    renderEditor(
      <>
        <ArtifactEditor id="ed3" artifacts={ARTIFACTS} isEditable={(a) => Boolean((a as Record<string, unknown>).draft)} onSubmit={(e) => (submitted = e)} />
        <button type="submit" form="ed3">go</button>
      </>,
    );
    await user.click(await screen.findByRole("tab", { name: /RFI/i }));
    await waitFor(() => expect(screen.getByDisplayValue("Confirm the beneficiary IBAN")).toBeTruthy());
    // switch the rfi tab to raw JSON and edit the blob directly
    await user.click(screen.getByRole("button", { name: /raw json/i }));
    const blob = screen.getByLabelText("rfi raw JSON") as HTMLTextAreaElement;
    await user.clear(blob);
    await user.click(blob);
    await user.paste(JSON.stringify({ channel: "email", questions: ["Q from raw"] }));
    // fill the required info_resolution outcome so the whole gate validates
    await user.click(screen.getByRole("tab", { name: /Info resolution/i }));
    await user.selectOptions(screen.getByLabelText(/Outcome/i), "cannot_obtain");
    await user.click(screen.getByText("go"));
    await waitFor(() => expect(submitted).toBeDefined());
    expect((submitted!.rfi as Record<string, unknown>).channel).toBe("email");
    expect((submitted!.rfi as Record<string, unknown>).questions).toEqual(["Q from raw"]);
    expect((submitted!.info_resolution as Record<string, unknown>).outcome).toBe("cannot_obtain");
  });

  it("does NOT submit the gate when a Raw-JSON toggle inside the form is clicked", async () => {
    // The read-only dossier tab renders ArtifactView (with its own Raw-JSON toggle) INSIDE ArtifactEditor's
    // <form>. A type-less <button> defaults to submit — clicking the toggle must NOT fire onSubmit/onDecide.
    // Editable artifacts are pre-filled VALID so that a stray submit WOULD reach onSubmit (making the bug
    // detectable, not masked by validation).
    const validArtifacts = [
      { name: "dossier", schema: "art.payment.enrich@1.0.0", data: { summary: "context" } },
      { name: "rfi", schema: "art.payment.rfi_request@1.0.0", data: { channel: "camt.027", questions: ["Q"] }, draft: true },
      { name: "info_resolution", schema: "art.payment.info_resolution@1.0.0", data: { outcome: "resolved" }, draft: true, authored_by_human: true },
    ] as unknown as PayloadArtifact[];
    server.use(schemaHandler());
    const user = userEvent.setup();
    let submitCount = 0;
    renderEditor(
      <>
        <ArtifactEditor id="ed4" artifacts={validArtifacts} isEditable={(a) => Boolean((a as Record<string, unknown>).draft)} onSubmit={() => (submitCount += 1)} />
        <button type="submit" form="ed4">go</button>
      </>,
    );
    // dossier is the default (read-only) tab → its ArtifactView Raw-JSON toggle sits inside the form
    const rawToggle = await screen.findByRole("button", { name: /raw json/i });
    await user.click(rawToggle);
    await new Promise((r) => setTimeout(r, 0));
    expect(submitCount).toBe(0);                        // toggling raw must not submit the decision…
    expect(screen.getByText(/"summary"/)).toBeTruthy(); // …it just expanded the raw JSON block

    // control: the explicit submit button DOES submit (proving the gate would have been submittable)
    await user.click(screen.getByText("go"));
    await waitFor(() => expect(submitCount).toBe(1));
  });

  it("blocks completion until the required human-authored field is filled", async () => {
    server.use(schemaHandler());
    const user = userEvent.setup();
    let submitted: Record<string, unknown> | undefined;

    renderEditor(
      <>
        <ArtifactEditor id="ed2" artifacts={ARTIFACTS} isEditable={(a) => Boolean((a as Record<string, unknown>).draft)} onSubmit={(e) => (submitted = e)} />
        <button type="submit" form="ed2">go</button>
      </>,
    );
    await waitFor(() => screen.getByRole("tab", { name: /Info resolution/i }));
    await user.click(screen.getByText("go")); // outcome still empty → zod required fails
    // give any async validation a tick; submit must not have fired
    await new Promise((r) => setTimeout(r, 0));
    expect(submitted).toBeUndefined();
  });
});
