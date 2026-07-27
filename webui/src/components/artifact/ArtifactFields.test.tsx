// ArtifactFields.test.tsx — Part B: schema-driven recursive form. Objects/arrays render as structured
// controls (not raw JSON); the assembled value is the structured artifact and validates against the schema.
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ArtifactForm } from "./ArtifactForm";
import { toDefault, parseValues, fieldKind } from "./ArtifactFields";
import type { JsonSchema } from "./schema";

const RFI_SCHEMA: JsonSchema = {
  type: "object",
  required: ["recipient", "channel", "questions"],
  properties: {
    recipient: {
      type: "object",
      required: ["party", "bic"],
      properties: { party: { enum: ["originator", "beneficiary_bank"] }, bic: { type: "string" } },
    },
    channel: { enum: ["camt.027", "mt199", "email"] },
    questions: { type: "array", items: { type: "string" } },
  },
};

const RFI_DATA = {
  recipient: { party: "beneficiary_bank", bic: "NWBKGB2L" },
  channel: "camt.027",
  questions: ["Confirm the beneficiary IBAN"],
};

describe("fieldKind", () => {
  it("classifies from schema, then value shape when the schema is absent", () => {
    expect(fieldKind({ type: "object", properties: { a: {} } }, undefined, "x")).toBe("object");
    expect(fieldKind({ type: "array", items: { type: "object", properties: {} } }, undefined, "x")).toBe("arrayObjects");
    expect(fieldKind({ type: "array", items: { type: "string" } }, undefined, "x")).toBe("arrayScalars");
    expect(fieldKind({ enum: ["a", "b"] }, undefined, "x")).toBe("enum");
    // schema absent → value shape decides (async-load window / freeform)
    expect(fieldKind(undefined, [{ a: 1 }], "x")).toBe("json");
    expect(fieldKind(undefined, "hi", "notes")).toBe("textarea");
    expect(fieldKind(undefined, "hi", "bic")).toBe("text");
  });
});

describe("toDefault / parseValues round-trip", () => {
  it("keeps structured nodes raw and restores them symmetrically", () => {
    const def = toDefault(RFI_SCHEMA, RFI_DATA, "rfi");
    // structured object/array stay as real objects/arrays for RHF nested fields / field arrays
    expect((def as Record<string, unknown>).channel).toBe("camt.027");
    expect(Array.isArray((def as Record<string, unknown>).questions)).toBe(true);
    const back = parseValues(RFI_SCHEMA, def, "rfi");
    expect(back).toEqual(RFI_DATA);
  });

  it("stringifies a freeform subtree (typed object, no properties) and parses it back symmetrically", () => {
    const freeform: JsonSchema = { type: "object" }; // no `properties` → freeform JSON leaf
    const def = toDefault(freeform, { nested: { a: 1 } }, "meta");
    expect(typeof def).toBe("string");
    expect(def).not.toContain("[object Object]");
    expect(parseValues(freeform, def, "meta")).toEqual({ nested: { a: 1 } });
  });
});

describe("ArtifactForm — structured editing (Part B)", () => {
  it("renders nested objects, enums and arrays as controls (not one JSON blob) and submits the structured artifact", async () => {
    const user = userEvent.setup();
    let submitted: Record<string, unknown> | undefined;
    render(
      <ArtifactForm id="rfi" schema={RFI_SCHEMA} defaultData={RFI_DATA} onSubmit={(d) => (submitted = d)} />,
    );

    // nested + enum + array-scalar controls are present, populated from the draft
    expect(screen.getByDisplayValue("NWBKGB2L")).toBeTruthy();          // recipient.bic (nested)
    expect(screen.getByDisplayValue("Confirm the beneficiary IBAN")).toBeTruthy(); // questions[0]

    // add a second question via the array add button
    await user.click(screen.getByRole("button", { name: /add/i }));
    const inputs = screen.getAllByDisplayValue("Confirm the beneficiary IBAN");
    expect(inputs.length).toBe(1); // still one; the new row is empty
    // fill the new question (last empty text input under the questions array)
    const qBoxes = screen.getAllByRole("textbox").filter((el) => (el as HTMLInputElement).value === "");
    const last = qBoxes[qBoxes.length - 1]!;
    await user.type(last, "Confirm the value date");

    // submit via a bare submit button bound to the form
    render(<button type="submit" form="rfi">go</button>);
    await user.click(screen.getByText("go"));

    expect(submitted).toBeDefined();
    expect(submitted!.channel).toBe("camt.027");
    expect(submitted!.recipient).toEqual({ party: "beneficiary_bank", bic: "NWBKGB2L" });
    expect(submitted!.questions).toEqual(["Confirm the beneficiary IBAN", "Confirm the value date"]);
  });

  it("toggles to a whole-artifact Raw JSON escape hatch and back", async () => {
    const user = userEvent.setup();
    render(<ArtifactForm id="rfi2" schema={RFI_SCHEMA} defaultData={RFI_DATA} onSubmit={() => {}} />);
    await user.click(screen.getByRole("button", { name: /raw json/i }));
    const raw = screen.getByLabelText("Raw JSON") as HTMLTextAreaElement;
    expect(JSON.parse(raw.value)).toEqual(RFI_DATA);
    await user.click(screen.getByRole("button", { name: /^form$/i }));
    expect(screen.getByDisplayValue("NWBKGB2L")).toBeTruthy(); // back to structured
  });
});
