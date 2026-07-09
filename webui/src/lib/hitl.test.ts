import { describe, it, expect } from "vitest";
import { decisionsForTask, HITL_MODE_META, decisionNeedsEdits } from "./hitl";

describe("HITL allowed-decisions mapping", () => {
  it("maps each mode to the contract's allowed decisions", () => {
    expect(HITL_MODE_META.review_after.allowedDecisions).toEqual(["approve", "edit_and_approve", "reject"]);
    expect(HITL_MODE_META.approve_result.allowedDecisions).toEqual(["approve", "reject"]);
    expect(HITL_MODE_META.approve_actions.allowedDecisions).toEqual(["approve", "reject"]);
    expect(HITL_MODE_META.manual.allowedDecisions).toEqual(["complete", "escalate"]);
  });

  it("prefers the task's allowed_decisions array over the mode default", () => {
    const decisions = decisionsForTask({ hitl_mode: "manual", allowed_decisions: ["complete"] });
    expect(decisions).toEqual(["complete"]);
  });

  it("falls back to the mode default when the array is absent", () => {
    expect(decisionsForTask({ hitl_mode: "review_after", allowed_decisions: null })).toEqual([
      "approve",
      "edit_and_approve",
      "reject",
    ]);
  });

  it("only edit_and_approve requires artifact edits", () => {
    expect(decisionNeedsEdits("edit_and_approve")).toBe(true);
    expect(decisionNeedsEdits("approve")).toBe(false);
  });

  it("maps every mode to a distinct UI variant", () => {
    const variants = Object.values(HITL_MODE_META).map((m) => m.variant);
    expect(new Set(variants).size).toBe(4);
  });
});
