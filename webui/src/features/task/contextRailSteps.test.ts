import { describe, it, expect } from "vitest";
import { deriveSteps } from "@/lib/steps";
import type { ProcessPackManifest, ActorLogEntry } from "@/api/types";

// A two-step pack so "viewed task" and "instance's current gate" can differ.
const pack = {
  bindings: [
    { element_id: "Task_A", element_kind: "serviceTask", hitl: { mode: "review_after" } },
    { element_id: "Task_B", element_kind: "serviceTask", hitl: { mode: "review_after" } },
  ],
} as unknown as ProcessPackManifest;

const acted = (element_id: string): ActorLogEntry =>
  ({ element_id, actor: "usr-1", kind: "human", at: "2099-01-01T00:00:00Z" } as ActorLogEntry);

describe("ContextRail step derivation (from the live instance, not the viewed task)", () => {
  it("marks the decided task done and the instance's open gate current", () => {
    // The analyst is *viewing* Task_A (just approved it), but the instance has
    // advanced: Task_A is in the actor_log and Task_B is the open gate.
    const steps = deriveSteps(pack, [acted("Task_A")], { currentElementId: "Task_B" });
    expect(steps.find((s) => s.element_id === "Task_A")!.state).toBe("done");
    expect(steps.find((s) => s.element_id === "Task_B")!.state).toBe("current");
  });

  it("does NOT pin current to the viewed task once it is decided", () => {
    // Regression guard for the old bug: passing the *viewed* task's element would
    // keep it "current" forever. Deriving from the instance (no open gate → none
    // current) is the fix.
    const steps = deriveSteps(pack, [acted("Task_A")], { currentElementId: undefined });
    expect(steps.find((s) => s.element_id === "Task_A")!.state).toBe("done");
    expect(steps.some((s) => s.state === "current")).toBe(false);
  });

  it("marks the last acted element failed on a failed instance", () => {
    const steps = deriveSteps(pack, [acted("Task_A"), acted("Task_B")], {
      failedElementId: "Task_B",
      terminal: true,
    });
    expect(steps.find((s) => s.element_id === "Task_B")!.state).toBe("failed");
    expect(steps.find((s) => s.element_id === "Task_A")!.state).toBe("done");
  });
});
