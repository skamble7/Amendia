// ArtifactForm.test.tsx — Part A: agent-draft hydration. A complex agent-drafted field (an array of
// objects, e.g. corrections on Task_ApproveRepair) must render as editable JSON on the FIRST paint — before
// the artifact schema resolves async — and never as "[object Object]". Previously the field was classified as
// text (schema-only), the raw array hit a text input, and only a remount (inbox back-nav / reload) fixed it.
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { ArtifactForm } from "./ArtifactForm";
import type { JsonSchema } from "./schema";

const CORRECTIONS = [
  { field: "creditor_account", before: "GB111", after: "GB222" },
  { field: "creditor_name", before: "ACME", after: "ACME LLC" },
];
const DATA = { corrections: CORRECTIONS, justification: "beneficiary IBAN corrected" };

const SCHEMA: JsonSchema = {
  type: "object",
  required: ["corrections"],
  properties: {
    corrections: {
      type: "array",
      items: {
        type: "object",
        properties: { field: { type: "string" }, before: { type: "string" }, after: { type: "string" } },
      },
    },
    justification: { type: "string" },
  },
};

function fieldValue(label: RegExp): string {
  return (screen.getByLabelText(label) as HTMLTextAreaElement).value;
}

describe("ArtifactForm — agent-draft hydration", () => {
  it("renders a complex field as JSON (never [object Object]) BEFORE the schema resolves", () => {
    render(<ArtifactForm id="f" schema={undefined} defaultData={DATA} onSubmit={() => {}} />);
    const value = fieldValue(/Corrections/);
    expect(value).not.toContain("[object Object]");
    expect(JSON.parse(value)).toEqual(CORRECTIONS); // structured value, editable as JSON immediately
  });

  it("re-hydrates when the schema resolves async — no remount needed", () => {
    const { rerender } = render(
      <ArtifactForm id="f" schema={undefined} defaultData={DATA} onSubmit={() => {}} />,
    );
    expect(fieldValue(/Corrections/)).not.toContain("[object Object]");

    // simulate the async schema arriving on a later render (react-query resolving)
    rerender(<ArtifactForm id="f" schema={SCHEMA} defaultData={DATA} onSubmit={() => {}} />);

    const value = fieldValue(/Corrections/);
    expect(value).not.toContain("[object Object]");
    expect(JSON.parse(value)).toEqual(CORRECTIONS);
  });
});
