import { describe, it, expect } from "vitest";
import { zodFromSchema } from "./zodFromSchema";
import type { JsonSchema } from "./schema";

const repairVerdict: JsonSchema = {
  type: "object",
  additionalProperties: false,
  required: ["repair_verdict", "confidence", "rationale"],
  properties: {
    repair_verdict: { type: "string", enum: ["repairable", "unrepairable", "needs_info"] },
    confidence: { type: "number", minimum: 0, maximum: 1 },
    rationale: { type: "string" },
    proposed_correction: {
      type: "object",
      required: ["field", "current_value", "proposed_value"],
      properties: {
        field: { type: "string" },
        current_value: { type: "string" },
        proposed_value: { type: "string" },
      },
    },
  },
};

describe("zodFromSchema", () => {
  const validator = zodFromSchema(repairVerdict);

  it("accepts a valid artifact", () => {
    const r = validator.safeParse({
      repair_verdict: "repairable",
      confidence: 0.9,
      rationale: "corrected via digit transposition",
    });
    expect(r.success).toBe(true);
  });

  it("rejects a missing required field", () => {
    const r = validator.safeParse({ repair_verdict: "repairable", confidence: 0.9 });
    expect(r.success).toBe(false);
  });

  it("rejects a value outside the enum", () => {
    const r = validator.safeParse({ repair_verdict: "maybe", confidence: 0.9, rationale: "x" });
    expect(r.success).toBe(false);
  });

  it("enforces number bounds (confidence 0..1)", () => {
    const r = validator.safeParse({ repair_verdict: "repairable", confidence: 1.5, rationale: "x" });
    expect(r.success).toBe(false);
  });

  it("treats non-required fields as optional", () => {
    const r = validator.safeParse({ repair_verdict: "needs_info", confidence: 0.2, rationale: "need address" });
    expect(r.success).toBe(true);
  });
});
