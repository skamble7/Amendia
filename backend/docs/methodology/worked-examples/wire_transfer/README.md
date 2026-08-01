# Wire-Transfer Exception — Copilot Onboarding Kit

The wire-transfer "unable-to-apply" repair process, packaged like the restaurant example so it onboards through
the **copilot** (ADR-052): a comprehensive BPMN + a live MCP server in, a validator-clean draft pack out, reviewed
in plain language and activated. This is the agentic *to-be* of the fuller narrative in
[`amendia_worked_scenario_wire_transfer.md`](./amendia_worked_scenario_wire_transfer.md).

The trigger (the external event contract) and triage (business routing) are **user-provided** — you paste them on
the copilot Start screen (the copilot infers the internal design, never the event contract). This folder
materializes both so they're ready to paste, exactly like the restaurant `party_seated` sample.

## Files

| File | What it is |
|---|---|
| `wire-repair-agentic.tobe.bpmn` | **The canonical executable BPMN** — the agentic target; upload this on Start. |
| `wire-repair-manual.asis.bpmn` | The current manual process (reference; not onboarded). |
| `wire-repair-process-diagram.svg` | Rendered diagram. |
| `wire-transfer-exception-reference.md` | Element-by-element binding/HITL reference. |
| `amendia_worked_scenario_wire_transfer.md` | The full document→design→onboard→execute narrative. |
| `schemas/art.payment.wire_exception.schema.json` | The trigger's **JSON Schema** (draft 2020-12, closed, canonical `$id`), derived from the registered `art.payment.wire_exception`. |
| `schemas/wire_exception.sample.json` | A realistic **sample event** — exactly what the stub emitter produces. Paste this into Start. |

The schema and sample agree with the authoritative registered trigger and with the event the stub actually emits
(`stub_exception_generator` `WireExceptionEnvelope` → the fetch-back envelope): same eleven fields, same required
set. That agreement is what prevents a trigger mismatch at dispatch.

## Copilot onboarding — the inputs to paste

On `/registry/onboard` (the copilot Start screen):

1. **Process name:** `Wire repair (agentic)`  ·  **Identifier (pack_key):** **`wire-copilot`**
   > Use a distinct pack key — the seeded, already-active `wire-repair-standard` owns the same trigger + reason
   > codes, so onboarding under `wire-repair-standard` would collide. `wire-copilot` keeps this draft separate.
2. **Process diagram (BPMN):** upload `wire-repair-agentic.tobe.bpmn`.
3. **Your tools (MCP server address):** `http://wirefix-mcp:8060/mcp`
   (the `mcp_stub/servers/wire_transfer_exception` server that backs the agent steps).
4. **The event that starts this process:** paste `schemas/wire_exception.sample.json` (or the JSON Schema).
5. **Which incoming events this process handles (triage):** the discriminator is **`exception_type`** (the event's
   kind) plus the repairable **`reason_codes`**. Set:
   - `exception_type` **eq** `unable_to_apply`

   To match the seeded pack exactly (tighten to repairable pacs.008 wires), author this composite in the technical
   detail view — the copilot's Start builder captures the single-leaf discriminator above:
   ```json
   { "all": [
       { "field": "exception_type",    "op": "eq",         "value": "unable_to_apply" },
       { "field": "payment.msg_type",  "op": "starts_with", "value": "pacs.008" },
       { "field": "reason_codes",      "op": "intersects", "value": ["AC01", "AC04", "RC01", "BE04"] }
   ] }
   ```

Generate → review the plain-language summary + gates → **Approve & go live**.
