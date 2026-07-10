import { describe, it, expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderApp } from "@/test/renderApp";
import { server } from "@/test/server";
import { SERVICE_BASE } from "@/api/config";
import { synthTask, synthException, synthInstanceDetail, synthPack, TEST_SCHEMA } from "@/test/fixtures";
import type { BpmnMarker } from "@/features/registry/BpmnViewer";

// bpmn-js needs real SVG rendering; stub the viewer so the test asserts the wiring
// (dialog opens, BPMN xml fetched, state markers passed) without the heavy canvas.
vi.mock("@/features/registry/BpmnViewer", () => ({
  BpmnViewer: ({ xml, markers }: { xml?: string; markers?: BpmnMarker[] }) => (
    <div data-testid="bpmn-viewer">
      xml:{xml ? "loaded" : "none"} markers:{markers?.length ?? 0}
    </div>
  ),
}));

const R = SERVICE_BASE.runtime;
const REG = SERVICE_BASE.registry;
const STUB = SERVICE_BASE.stub;

describe("Task detail — BPMN process diagram", () => {
  it("launches the actual BPMN diagram with process-state markers from the progress card", async () => {
    server.use(
      http.get(`${R}/hitl-tasks/diag1`, () => HttpResponse.json(synthTask({ task_id: "diag1" }))),
      http.get(`${STUB}/exceptions/:id`, () => HttpResponse.json(synthException())),
      http.get(`${REG}/packs/:key/:version`, () => HttpResponse.json(synthPack)),
      http.get(`${REG}/packs/:key/:version/bpmn`, () => HttpResponse.text("<definitions/>")),
      http.get(`${REG}/artifact-schemas/:key/:version`, () => HttpResponse.json({ json_schema: TEST_SCHEMA })),
      http.get(`${R}/instances/:id`, () => HttpResponse.json(synthInstanceDetail())),
    );
    const user = userEvent.setup();
    renderApp("/inbox/diag1", "analyst-1");

    // The diagram is not mounted until the operator clicks the expand icon.
    const open = await screen.findByRole("button", { name: /open bpmn process diagram/i });
    expect(screen.queryByTestId("bpmn-viewer")).not.toBeInTheDocument();

    await user.click(open);

    // Opens in place (not a modal): the BPMN view replaces the task layout.
    const viewer = await screen.findByTestId("bpmn-viewer");
    expect(screen.getByText(/Process diagram · BPMN/i)).toBeInTheDocument();
    expect(viewer).toHaveTextContent("xml:loaded");
    expect(viewer).toHaveTextContent("markers:1"); // synthPack has one binding → one step marker

    // "Back to task" restores the task view.
    await user.click(screen.getByRole("button", { name: /back to task/i }));
    await screen.findByText(/Claim this task/i);
    expect(screen.queryByTestId("bpmn-viewer")).not.toBeInTheDocument();
  });
});
