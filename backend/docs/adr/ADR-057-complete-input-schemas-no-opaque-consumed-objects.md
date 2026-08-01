# ADR-057 — Complete input schemas: opaque consumed objects are non-compliant; HITL forms derive from declared shapes

**Status:** Accepted (2026-08-01)
**Related:** ADR-050 (human-authored artifacts), ADR-054 (schema refiner / no raw-JSON HITL forms), the MCP
Implementor Guideline, `mcp_introspect.check_compliance`, copilot `_derive_human_artifacts`.

## Context

Amendia derives a human-authored artifact's schema from the **input shape of the tool(s) that consume it** —
"derive, don't invent." A HITL approval form is only as clean as that derived schema. Two real processes hit the
same failure: a human-authored field (wire `approved_repair.proposed_value`, via `apply_repair.repair`) renders as
a **raw JSON editor**, defeating ADR-054's whole point ("no raw-JSON blob for the business user").

Root cause is at the source. The MCP tool's `inputSchema` declares the consumed field as an **opaque object** —
`{"type": "object"}` with no `properties`. The reference stubs do this deliberately (an `_open()` helper, "inputs
are permissive"). Amendia can't render a concrete form for a shape the tool never declared, and `check_compliance`
today enforces only R1–R4 (schemas present, root object, no external `$ref`) — it does not flag opaque objects, so
these tools onboard clean and fail the operator later, at form-fill time.

The MCP handshake already captures the *complete declared* schema; the lever is requiring authors to *declare*
completely. But Amendia does not own third-party MCP servers, and some human artifacts have **no** tool consumer at
all (a terminal decision) — so the tool schema can't be the *only* source of truth.

## Decision

A layered contract, in priority order:

1. **Prefer the tool's declared schema — and require completeness.** A tool input property typed `object` MUST
   declare its `properties` (no opaque objects). This is added to the MCP Implementor Guideline (schema-shape
   conventions) and enforced by `check_compliance` as a **warning-level finding**, surfaced at introspection /
   the Capabilities step ("field X on tool Y is an untyped object — its HITL form will be a raw editor unless the
   schema declares its properties"). It is a **warning, not a hard reject**: Amendia cannot force a third-party
   server to comply, so onboarding proceeds with the fallback below.

2. **Graceful fallback where the tool is opaque or has no consumer.** The copilot's derivation keeps the tool's
   **type** authoritative, but when a consumed field is an opaque object the LLM's inferred (or the operator's
   refined) nested `properties` **fill** that inner shape — a labeled form instead of a blob. This never changes
   the tool-required type; it only supplies inner structure the tool left unspecified (a tool that accepts any
   object accepts a labeled sub-form). The operator refiner can author nested object properties as the final
   escape hatch.

3. **The reference stubs must obey the guideline.** The `wire_transfer_exception` and `restaurant_dinein` stubs
   declare the nested shapes for every input field that backs a human-authored artifact (keeping those input
   objects tolerant of the extra decision fields a human records, so a whole-object input map does not 400).

## Consequences

- **+** Where a tool is well-typed, HITL forms are concrete and deterministic — no inference, no blob.
- **+** Authors get an actionable warning at onboarding, not a runtime surprise.
- **+** Servers Amendia doesn't control still onboard, and produce a usable (inferred/refined) form rather than a blob.
- **+** The reference stubs become a correct example of the guideline.
- **−** The completeness rule is advisory (warning) for third-party tools — not enforceable; the fallback carries them.
- **−** Slightly more work for tool authors (declare nested shapes) — but that is the shape Amendia needs anyway.

## Non-goals

- Hard-rejecting non-compliant third-party tools (warn + fall back instead).
- Changing what the handshake captures (it already captures the full declared schema).
- Replacing operator refinement — it remains the final tailoring of the human form.
