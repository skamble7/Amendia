# Amendia MCP Implementor Guideline

**Status:** normative for MCP servers onboarded as Amendia capabilities of `kind: mcp`.
**Audience:** teams building MCP servers whose tools will be registered as Amendia capabilities via the process-pack onboarding wizard.
**Companion documents:** `amendia_platform_contracts_v1.md` (§2 Capability descriptor, §3 Artifact schema registry), `amendia_contracts_reference.md` (§4, §5).

---

## 1. Why this guideline exists

When a bank onboards a process pack, the onboarding wizard points at a running MCP server, calls `tools/list`, and turns each selected tool into Amendia platform objects: the tool's `inputSchema` becomes an input **artifact schema**, its `outputSchema` becomes an output **artifact schema**, and the tool itself becomes one **capability** of `kind: mcp` whose `runtime.tools` whitelists exactly that tool.

That inference only works if the server describes itself completely and in a shape Amendia's registry accepts. Amendia's registry is a closed, auditable universe: every artifact a capability produces is validated against a pinned JSON Schema at execution time, and a write that fails validation fails the task rather than silently coercing. A tool that returns an undeclared or loosely-typed payload cannot be onboarded, or worse, onboards and then fails at runtime inside a live payment-exception process.

This guideline states what a compliant Amendia MCP server must provide. The onboarding wizard's introspection step validates against these rules and refuses (or flags) any tool that violates them.

---

## 2. The core requirement — every tool is fully self-describing

Amendia infers artifacts from schemas, not from prose. Therefore:

**R1 — Every tool MUST declare an `inputSchema`.** It must be a JSON Schema object with root `"type": "object"`. A tool that takes no arguments still declares `{"type": "object", "properties": {}, "additionalProperties": false}`.

**R2 — Every tool MUST declare an `outputSchema`.** This is the requirement most MCP servers omit today, and it is non-negotiable for Amendia. The runtime needs a typed shape to validate the tool's result against and to render in human-in-the-loop review screens. A tool with no `outputSchema` cannot be onboarded — the wizard will list it as non-compliant.

**R3 — Action-oriented (side-effectful) tools MUST return an acknowledgement.** A tool that changes state outside Amendia (releases a payment, sends a message, writes to a system of record) must still produce a typed output — it may not "return nothing." At minimum it returns an acknowledgement object so the process has a committable, auditable artifact recording that the action was taken. See §4.

**R4 — Schemas MUST be self-contained.** No `$ref` to external URLs. Internal `$ref` into a local `$defs` block is fine; anything reaching outside the document is rejected (Amendia only permits `$ref` to already-registered Amendia schema `$id`s, which your server cannot know at authoring time).

Rationale for all four: they are exactly the preconditions the registry enforces at artifact registration (`amendia_platform_contracts_v1.md` §3) and at capability registration (§2). Meeting them at the server means the wizard's inference is a rename, not a repair.

---

## 3. Schema shape conventions

The wizard rewrites each tool schema into an Amendia artifact registration. You reduce friction (and surprises) by authoring schemas that already match Amendia's house style:

1. **Root is an object.** `"type": "object"` at the top level of both `inputSchema` and `outputSchema`. Amendia artifacts are always objects; a tool that logically returns a bare array should wrap it (`{"items": [...]}`).
2. **Closed shapes.** Set `"additionalProperties": false` on every object you control. Amendia warns on open artifacts because open shapes let agent/tool outputs drift undetected. Closed shapes keep outputs honest.
3. **Draft 2020-12.** Author to JSON Schema draft 2020-12. The wizard sets `$schema` and injects the canonical `$id` for you — do not hardcode an Amendia `$id`, and do not rely on your own `$id` surviving (it is overwritten).
4. **Mark required fields that carry decisions.** Any field a downstream BPMN gateway will branch on must be `required`. Amendia's pack validation rejects a gateway that reads an optional field, because a gateway must never branch on possibly-absent data. If your output drives a decision (e.g. `repair_verdict`, `screening_result`), make that field required.
5. **Prefer enums and bounded types.** Enumerations, `minimum`/`maximum`, and explicit formats survive into the artifact schema and make both validation and HITL rendering precise.
6. **Name fields in `snake_case`** and keep names stable across versions — a rename is a breaking change under Amendia's semver rules.

---

## 4. Action-oriented tools — the acknowledgement contract

An action-oriented tool is one whose descriptor will be classified `side_effect: side_effectful` in Amendia. (Amendia cannot infer this from MCP; the onboarding operator sets it. But you should design as if any tool that mutates the outside world is side-effectful, because the operator will mark it so, and Amendia policy then forces the binding to run behind an `approve_actions` or stricter human gate.)

Such a tool must return a typed acknowledgement so the process has something to commit and audit even when the "real" result is just "done." The recommended minimum shape:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["acknowledged", "action_id", "status"],
  "properties": {
    "acknowledged": { "type": "boolean", "description": "True once the action was accepted/performed" },
    "action_id":    { "type": "string", "description": "Server-side id for the performed action; enables idempotent retry and audit" },
    "status":       { "enum": ["performed", "queued", "rejected"] },
    "detail":       { "type": "string", "description": "Human-readable outcome note" },
    "performed_at": { "type": "string", "format": "date-time" }
  }
}
```

You may extend this with action-specific fields (a payment reference, a message id), but the four required fields above are the floor. `action_id` matters twice: it is the anchor for idempotent retry, and it is what the four-eyes audit record ties the human approval to.

Read-only tools (investigation, screening, enrichment) are not held to the acknowledgement shape — their `outputSchema` simply describes the data they return — but they are still bound by R2 (they must declare that output schema).

---

## 4a. Signalling a modeled business error

Amendia distinguishes two kinds of failure, and your tool result decides which one Amendia sees:

- A **technical / protocol error** — the tool couldn't run: a JSON-RPC `error` object in the `tools/call` reply, an HTTP failure, a timeout, a crash. Amendia treats this as a *technical* failure: the task fails or retries per its idempotency policy.
- A **modeled business error** — the tool *ran* and reports a legitimate, process-anticipated outcome the diagram already has a branch for: the payment was **rejected**, screening returned a **hit**, the request had **insufficient information**. This is not a failure of the tool; it is a first-class result the process routes to a BPMN **error boundary event** (a return/rework path), and the process instance stays running.

**How to signal a modeled business error.** Return a normal MCP `tools/call` result with **`isError: true`** and a conventional **`error_code`** the process can match:

```json
{
  "isError": true,
  "structuredContent": { "error_code": "PAYMENT_REJECTED", "detail": { "uetr": "…", "reason": "beneficiary account closed" } }
}
```

- The `error_code` string must equal the `errorCode` of the `<bpmn:error>` the diagram's error boundary references (e.g. `PAYMENT_REJECTED`, `SCREENING_HIT`, `NEEDS_INFO`). Amendia routes on an exact match; an unmatched code falls to a catch-all boundary if one exists, else the instance fails. Keep these codes stable — they are part of your tool's contract, like field names.
- Put `error_code` in `structuredContent.error_code` (preferred) or in a `content[]` JSON block. If `isError` is set without any derivable code, Amendia still treats it as a business error under the generic code `MCP_TOOL_ERROR` (so a catch-all can still catch it) — but always emit an explicit code.
- For an **action-oriented tool** (§4), a rejected action is the same signal: return `isError: true` with `status: "rejected"` and the `error_code` in the acknowledgement's `structuredContent`.

**Do not** use `isError` for a transport/validation problem, and **do not** encode a business rejection as a JSON-RPC `error` — that inverts the two categories and Amendia will fail the instance instead of routing it. When in doubt: *the tool ran and has an opinion about the business outcome* → `isError: true` + `error_code`; *the tool could not produce a result* → protocol/HTTP error.

---

## 5. Endpoint, transport, and headers

Amendia's capability descriptor is self-descriptive (ADR-024): the capability carries the MCP server `endpoint` directly, with no config-forge indirection. Consequences for you:

- **The server must be reachable at onboarding time and at run time.** The wizard performs a live `tools/list` during onboarding; the runtime connects at execution. The endpoint you provide is environment-specific — provide the URL that the Amendia deployment (not a developer laptop) will call.
- **Default transport is `streamable_http`.** `sse` and `stdio` are also accepted by the descriptor; `streamable_http` is the expected default for an onboarded HTTP MCP server.
- **Headers carry no literal secrets.** The descriptor's `headers` accepts non-secret headers or secret *references* (`env:`, `file:`, `vault:`) only — never a literal token. If your server needs auth, expose it as a header populated from a secret reference the deployment resolves.
- **Tool whitelisting is enforced.** Each onboarded capability whitelists exactly the tools it may call. A server may expose many tools; a capability sees only the ones its `runtime.tools` names. Keep tools single-purpose so this whitelist stays meaningful.

---

## 6. Versioning and stability

Once a capability and its artifacts are registered and a pack is activated, they are pinned and immutable — a live pack runs exactly the versions it activated with. So:

- **Do not silently change a tool's input or output shape.** A change to `inputSchema`/`outputSchema` is a new artifact version in Amendia and must be re-onboarded; changing the shape under a stable endpoint will cause runtime validation failures against the pinned schema.
- **Additive changes only, within a version.** New *optional* input fields and widened output enums are backward-compatible (a minor bump). Removing/renaming fields, adding required fields, or narrowing types is breaking (a major bump) and requires a fresh onboarding.
- **Keep tool names stable.** The tool name seeds the capability id and the artifact names; renaming a tool is effectively a new capability.

---

## 7. Pre-onboarding self-check

Before handing an MCP server URL to the onboarding wizard, confirm each tool you intend to onboard:

- [ ] Declares `inputSchema` with root `type: object`.
- [ ] Declares `outputSchema` with root `type: object`.
- [ ] If it mutates outside state, its output includes the acknowledgement fields (`acknowledged`, `action_id`, `status`).
- [ ] Uses no external `$ref` (internal `$defs` only).
- [ ] Sets `additionalProperties: false` on objects it owns.
- [ ] Marks as `required` every field a downstream gateway or consumer depends on.
- [ ] Uses stable `snake_case` field and tool names.
- [ ] Signals any diagram-anticipated failure as a modeled business error (`isError: true` + a stable `error_code`), not as a JSON-RPC/transport error (§4a).
- [ ] Is reachable at the deployment-facing endpoint over the declared transport.

A tool that clears this list onboards as a rename-and-confirm. A tool that misses R1–R4 is flagged non-compliant by the wizard and cannot be committed into a pack.
