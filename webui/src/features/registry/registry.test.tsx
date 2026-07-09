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
  it("validates and groups the error under its validator stage, blocking activation", async () => {
    server.use(
      http.post(`${REG}/packs`, async ({ request }) => HttpResponse.json(await request.json(), { status: 201 })),
      http.put(`${REG}/packs/:key/:version/bpmn`, () => HttpResponse.json({ bpmn_sha256: "x" })),
      http.post(`${REG}/packs/:key/:version/validate`, () => HttpResponse.json(synthValidationReport)),
    );
    const user = userEvent.setup();
    renderApp("/registry/onboard", "owner-1");

    await user.click(await screen.findByRole("button", { name: /next: bpmn/i }));
    await user.click(await screen.findByRole("button", { name: /^validate$/i }));

    expect(await screen.findByText(/test_side_effect_error/)).toBeInTheDocument();
    expect(await screen.findByText(/HITL & side-effect policy/)).toBeInTheDocument();
    expect(await screen.findByText(/must be resolved before activation/i)).toBeInTheDocument();
  });
});
