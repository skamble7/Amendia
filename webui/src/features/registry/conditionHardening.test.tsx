import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConditionNormalizationNotice, GatewayConditionIssues } from "./OnboardingWizard";
import type { ValidationFinding } from "@/api/services/registry";

describe("ConditionNormalizationNotice (upload banner)", () => {
  it("renders a before/after notice when Tier-1 auto-converted conditions", () => {
    render(
      <ConditionNormalizationNotice
        normalizations={[
          { gateway_id: "Gateway_A", flow_id: "f1", from: '${decision == "Proceed"}', to: 'decision == "Proceed"', changes: ["unwrapped ${…} expression"] },
        ]}
      />,
    );
    expect(screen.getByText(/Converted 1 gateway condition from Camunda/i)).toBeInTheDocument();
    expect(screen.getByText('${decision == "Proceed"}')).toBeInTheDocument();
    expect(screen.getByText('decision == "Proceed"')).toBeInTheDocument();
  });

  it("renders nothing when there were no conversions", () => {
    const { container } = render(<ConditionNormalizationNotice normalizations={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("GatewayConditionIssues (guided, blocking fix)", () => {
  const missingField: ValidationFinding = {
    code: "gateway_condition_grammar", severity: "error", stage: 6, element_id: "Gateway_A", path: null,
    reason: "missing_field",
    message: "gateway 'Gateway_A' condition 'decision == \"Proceed\"' compares the whole 'decision' output object to a string and can never branch — target a field. e.g. decision.rbo_decision = \"approve\"",
    suggestion: { obj: "decision", candidate_fields: ["rbo_decision"], enum_values: { rbo_decision: ["approve", "reject"] }, condition: 'decision.rbo_decision = "approve"' },
  };

  it("shows the guided message + a concrete suggestion, and Apply pre-fills the variable", async () => {
    const onApply = vi.fn();
    render(<GatewayConditionIssues issues={[missingField]} onApply={onApply} />);
    expect(screen.getByText(/can never branch/i)).toBeInTheDocument();
    expect(screen.getByText('decision.rbo_decision = "approve"')).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: /Apply/i }));
    expect(onApply).toHaveBeenCalledWith('decision.rbo_decision = "approve"');
  });

  it("offers no Apply for a placeholder suggestion (author must choose the value)", () => {
    const placeholder: ValidationFinding = {
      ...missingField, reason: "unsupported_operator",
      message: "only string comparison with = / == / != is supported",
      suggestion: { obj: "decision", candidate_fields: [], condition: 'decision.<field> = "<category>"' },
    };
    render(<GatewayConditionIssues issues={[placeholder]} onApply={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /Apply/i })).not.toBeInTheDocument();
  });

  it("renders nothing when a gateway has no issues", () => {
    const { container } = render(<GatewayConditionIssues issues={[]} onApply={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});
