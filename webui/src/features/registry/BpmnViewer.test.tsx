// BpmnViewer.test.tsx — the zoom/pan controls (ADR-052 2c Part D). bpmn-js needs real SVG layout jsdom lacks,
// so we mock the NavigatedViewer with a fake canvas whose `zoom` is a spy and assert the +/−/fit buttons drive it.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BpmnViewer } from "./BpmnViewer";

const zoom = vi.fn((arg?: string | number) => (typeof arg === "number" ? arg : 1));
const canvas = { zoom, addMarker: vi.fn() };

vi.mock("bpmn-js/dist/bpmn-navigated-viewer.production.min.js", () => ({
  default: class {
    async importXML() { return { warnings: [] }; }
    get() { return canvas; }
    destroy() {}
  },
}));

describe("BpmnViewer — zoom controls", () => {
  beforeEach(() => zoom.mockClear());

  it("fits on load and the buttons zoom in / out / fit", async () => {
    const user = userEvent.setup();
    render(<BpmnViewer xml="<bpmn:definitions/>" controls />);

    // the viewer fits to the viewport once imported
    await waitFor(() => expect(zoom).toHaveBeenCalledWith("fit-viewport"));

    await user.click(screen.getByRole("button", { name: /zoom in/i }));
    expect(zoom).toHaveBeenLastCalledWith(expect.closeTo(1.2, 5));   // 1 * 1.2

    await user.click(screen.getByRole("button", { name: /zoom out/i }));
    // zoom() now reports 1 (the fake canvas ignores state) → 1 / 1.2 ≈ 0.833
    expect(zoom).toHaveBeenLastCalledWith(expect.closeTo(1 / 1.2, 5));

    await user.click(screen.getByRole("button", { name: /fit to view/i }));
    expect(zoom).toHaveBeenLastCalledWith("fit-viewport");
  });

  it("omits the controls when not requested", async () => {
    render(<BpmnViewer xml="<bpmn:definitions/>" />);
    await waitFor(() => expect(zoom).toHaveBeenCalledWith("fit-viewport"));
    expect(screen.queryByRole("button", { name: /zoom in/i })).not.toBeInTheDocument();
  });
});
