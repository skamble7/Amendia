// ArtifactForm.test.tsx — Part A: agent-draft hydration. A complex agent-drafted field (an array of
// objects, e.g. corrections on Task_ApproveRepair) must render without "[object Object]" on the FIRST paint —
// before the artifact schema resolves async — and must re-hydrate (no remount) once the schema arrives.
// Previously the field was classified from the schema only, the raw array hit a text input, and only a
// remount (inbox back-nav / reload) fixed it.
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

  it("re-hydrates into structured fields when the schema resolves async — no remount, no [object Object]", () => {
    const { rerender, container } = render(
      <ArtifactForm id="f" schema={undefined} defaultData={DATA} onSubmit={() => {}} />,
    );
    expect(fieldValue(/Corrections/)).not.toContain("[object Object]"); // pre-schema: JSON textarea

    // simulate the async schema arriving on a later render (react-query resolving)
    rerender(<ArtifactForm id="f" schema={SCHEMA} defaultData={DATA} onSubmit={() => {}} />);

    // post-schema: the array-of-objects renders as structured rows populated from the draft (Part B),
    // re-hydrated without a remount — the correction values are in real inputs, never "[object Object]".
    expect(screen.getByDisplayValue("creditor_account")).toBeTruthy();
    expect(screen.getByDisplayValue("GB111")).toBeTruthy();
    expect(screen.getByDisplayValue("GB222")).toBeTruthy();
    expect(container.textContent).not.toContain("[object Object]");
  });
});
