# Amendia Platform Contracts v1

The five contracts that connect the process-registry service and the agent runtime. The registry stores and validates declarations in these formats; the runtime interprets them. Everything else (onboarding journey, runtime internals) builds on top without changing these shapes.

Status: draft for review. All schemas are JSON Schema draft 2020-12.

---

## 0. Shared conventions

**Identifiers.** Dotted, namespaced, lowercase: capabilities `cap.<domain>.<name>`, roles `role.<domain>.<name>`, artifact schemas `art.<domain>.<name>`. Pack keys are kebab-case (`wire-repair-standard`).

**Versioning.** Semver everywhere. A *reference* to a versioned thing is written `<id>@<range>` (npm-style range: `1.2.0`, `^1.0.0`, `>=1.0 <2.0`) in `requires` positions, and pinned exact (`<id>@1.2.0`) in *resolved/runtime* positions. The registry resolves ranges to pins at pack activation time.

**Timestamps** are UTC ISO-8601. **Envelope kinship:** every event shares the base fields `event_id` (uuid4), `occurred_at`, `schema_version`. Routing keys always come from `amendia_common.events.rk()`: `<service>.<event>.v1` on the `amendia.events` topic exchange.

**HITL modes** (used by contracts 1, 2, 5):

| mode | semantics |
|---|---|
| `none` | fully autonomous; no human touchpoint |
| `review_after` | capability runs; its output artifact is held for human review (approve / edit-and-approve / reject) before being committed to process state |
| `approve_result` | capability runs; result must be approved/rejected as-is before downstream elements activate (no edits) |
| `approve_actions` | capability *proposes* side-effectful actions; a human must approve before the runtime executes them (pre-execution gate) |
| `manual` | a human performs the task itself; an assist capability may pre-draft content |

Ordering of strictness for policy checks: `none < review_after ≤ approve_result < approve_actions ≈ manual`.

---

## 1. ProcessPack manifest

The versioned onboarding unit a bank submits: BPMN reference + bindings + triage rules + declared dependencies. The BPMN XML itself stays byte-stable and annotation-free; all execution metadata lives here.

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://amendia.dev/schemas/platform/process-pack-manifest/1.0.json",
  "title": "ProcessPackManifest",
  "type": "object",
  "required": ["manifest_version", "pack_key", "version", "title", "process",
               "triage_rules", "requires_capabilities", "artifacts", "bindings", "status"],
  "additionalProperties": false,
  "properties": {
    "manifest_version": { "const": "1.0" },
    "pack_key": { "type": "string", "pattern": "^[a-z][a-z0-9-]*$" },
    "version": { "type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+$" },
    "title": { "type": "string" },
    "description": { "type": "string" },
    "process": {
      "type": "object",
      "required": ["bpmn_file", "process_id", "bpmn_sha256"],
      "additionalProperties": false,
      "properties": {
        "bpmn_file": { "type": "string", "description": "Path/object key of the BPMN 2.0 XML stored alongside the manifest" },
        "process_id": { "type": "string", "description": "bpmn:process/@id inside the file" },
        "bpmn_sha256": { "type": "string", "pattern": "^[a-f0-9]{64}$" }
      }
    },
    "triage_rules": {
      "type": "array", "minItems": 1,
      "items": { "$ref": "#/$defs/triageRule" }
    },
    "requires_capabilities": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["ref"],
        "additionalProperties": false,
        "properties": {
          "ref": { "type": "string", "pattern": "^cap\\.[a-z0-9_.]+@.+$" },
          "resolved": { "type": "string", "pattern": "^cap\\.[a-z0-9_.]+@\\d+\\.\\d+\\.\\d+$",
                        "description": "Pinned by the registry at activation; absent while draft" }
        }
      }
    },
    "artifacts": {
      "description": "All artifact schemas this pack's bindings read or write.",
      "type": "array",
      "items": { "type": "string", "pattern": "^art\\.[a-z0-9_.]+@.+$" }
    },
    "bindings": {
      "type": "array", "minItems": 1,
      "items": { "$ref": "#/$defs/binding" }
    },
    "gateway_variables": {
      "description": "Declares which artifact fields the BPMN gateway FEEL expressions read, so validation can check they are produced upstream.",
      "type": "array",
      "items": {
        "type": "object",
        "required": ["gateway_id", "variable", "source_artifact"],
        "additionalProperties": false,
        "properties": {
          "gateway_id": { "type": "string" },
          "variable": { "type": "string", "description": "e.g. beneficiary.repair_verdict" },
          "source_artifact": { "type": "string", "pattern": "^art\\." }
        }
      }
    },
    "policies": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "separation_of_duties": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["constraint", "elements"],
            "properties": {
              "constraint": { "enum": ["distinct_actor"] },
              "elements": { "type": "array", "items": { "type": "string" }, "minItems": 2 }
            }
          }
        }
      }
    },
    "status": { "enum": ["draft", "validated", "active", "deprecated"] },
    "created_by": { "type": "string" },
    "created_at": { "type": "string", "format": "date-time" }
  },

  "$defs": {
    "triageRule": {
      "type": "object",
      "required": ["rule_id", "priority", "when"],
      "additionalProperties": false,
      "properties": {
        "rule_id": { "type": "string" },
        "priority": { "type": "integer", "description": "Lower number wins when multiple packs match" },
        "description": { "type": "string" },
        "when": { "$ref": "#/$defs/predicate" }
      }
    },
    "predicate": {
      "description": "Boolean combinator tree over envelope fields (dot-paths into the normalized exception).",
      "oneOf": [
        { "type": "object", "required": ["all"], "additionalProperties": false,
          "properties": { "all": { "type": "array", "items": { "$ref": "#/$defs/predicate" }, "minItems": 1 } } },
        { "type": "object", "required": ["any"], "additionalProperties": false,
          "properties": { "any": { "type": "array", "items": { "$ref": "#/$defs/predicate" }, "minItems": 1 } } },
        { "type": "object", "required": ["not"], "additionalProperties": false,
          "properties": { "not": { "$ref": "#/$defs/predicate" } } },
        { "type": "object", "required": ["field", "op"], "additionalProperties": false,
          "properties": {
            "field": { "type": "string" },
            "op": { "enum": ["eq", "ne", "in", "starts_with", "intersects", "exists", "gt", "gte", "lt", "lte"] },
            "value": {}
          } }
      ]
    },
    "binding": {
      "type": "object",
      "required": ["element_id", "element_kind", "executor", "hitl"],
      "additionalProperties": false,
      "properties": {
        "element_id": { "type": "string", "description": "Must match a flow node id in the BPMN" },
        "element_kind": { "enum": ["serviceTask", "userTask"] },
        "executor": {
          "oneOf": [
            { "type": "object", "required": ["type", "capability"], "additionalProperties": false,
              "properties": {
                "type": { "const": "capability" },
                "capability": { "type": "string", "pattern": "^cap\\..+@.+$" } } },
            { "type": "object", "required": ["type", "role"], "additionalProperties": false,
              "properties": {
                "type": { "const": "human" },
                "role": { "type": "string", "pattern": "^role\\." },
                "assist_capability": { "type": "string", "pattern": "^cap\\..+@.+$" } } }
          ]
        },
        "hitl": {
          "type": "object",
          "required": ["mode"],
          "additionalProperties": false,
          "properties": {
            "mode": { "enum": ["none", "review_after", "approve_result", "approve_actions", "manual"] },
            "role": { "type": "string", "pattern": "^role\\.",
                      "description": "Who reviews/approves. Required for every mode except none." }
          }
        },
        "inputs":  { "type": "array", "items": { "$ref": "#/$defs/artifactIO" } },
        "outputs": { "type": "array", "items": { "$ref": "#/$defs/artifactIO" } }
      }
    },
    "artifactIO": {
      "type": "object",
      "required": ["name", "schema"],
      "additionalProperties": false,
      "properties": {
        "name":   { "type": "string", "description": "Key in process state, e.g. 'beneficiary'" },
        "schema": { "type": "string", "pattern": "^art\\..+@.+$" },
        "required": { "type": "boolean", "default": true }
      }
    }
  }
}
```

### Example (abridged, `wire-repair-standard@1.0.0`)

```json
{
  "manifest_version": "1.0",
  "pack_key": "wire-repair-standard",
  "version": "1.0.0",
  "title": "Wire Transfer Exception — Unable to Apply / Repair",
  "process": {
    "bpmn_file": "wire-repair.bpmn",
    "process_id": "Process_WireRepairStandard",
    "bpmn_sha256": "3c1f…"
  },
  "triage_rules": [
    {
      "rule_id": "wire-uta-repairable-codes",
      "priority": 100,
      "when": {
        "all": [
          { "field": "exception_type", "op": "eq", "value": "unable_to_apply" },
          { "field": "payment.msg_type", "op": "starts_with", "value": "pacs.008" },
          { "field": "reason_codes", "op": "intersects", "value": ["AC01", "AC04", "RC01", "BE04"] }
        ]
      }
    }
  ],
  "requires_capabilities": [
    { "ref": "cap.payment.enrich_investigation@^1.0.0" },
    { "ref": "cap.payment.assess_beneficiary@^1.0.0" },
    { "ref": "cap.payment.draft_repair@^1.0.0" },
    { "ref": "cap.payment.sanctions_screen@^1.0.0" },
    { "ref": "cap.payment.apply_repair@^1.0.0" }
  ],
  "artifacts": [
    "art.payment.investigation_dossier@^1.0.0",
    "art.payment.repair_verdict@^1.0.0",
    "art.payment.repair_instruction@^1.0.0",
    "art.compliance.screening_result@^1.0.0"
  ],
  "bindings": [
    {
      "element_id": "Task_EnrichPayment",
      "element_kind": "serviceTask",
      "executor": { "type": "capability", "capability": "cap.payment.enrich_investigation@^1.0.0" },
      "hitl": { "mode": "none" },
      "inputs":  [],
      "outputs": [ { "name": "dossier", "schema": "art.payment.investigation_dossier@^1.0.0" } ]
    },
    {
      "element_id": "Task_AssessRepairability",
      "element_kind": "serviceTask",
      "executor": { "type": "capability", "capability": "cap.payment.assess_beneficiary@^1.0.0" },
      "hitl": { "mode": "review_after", "role": "role.payments.ops_analyst" },
      "inputs":  [ { "name": "dossier", "schema": "art.payment.investigation_dossier@^1.0.0" } ],
      "outputs": [ { "name": "beneficiary", "schema": "art.payment.repair_verdict@^1.0.0" } ]
    },
    {
      "element_id": "Task_ObtainInfo",
      "element_kind": "userTask",
      "executor": { "type": "human", "role": "role.payments.ops_analyst",
                    "assist_capability": "cap.payment.draft_rfi@^1.0.0" },
      "hitl": { "mode": "manual", "role": "role.payments.ops_analyst" }
    },
    {
      "element_id": "Task_ApproveRepair",
      "element_kind": "userTask",
      "executor": { "type": "human", "role": "role.payments.ops_approver" },
      "hitl": { "mode": "manual", "role": "role.payments.ops_approver" },
      "inputs": [ { "name": "repair", "schema": "art.payment.repair_instruction@^1.0.0" } ]
    },
    {
      "element_id": "Task_ApplyRepair",
      "element_kind": "serviceTask",
      "executor": { "type": "capability", "capability": "cap.payment.apply_repair@^1.0.0" },
      "hitl": { "mode": "approve_actions", "role": "role.payments.ops_approver" },
      "inputs": [ { "name": "repair", "schema": "art.payment.repair_instruction@^1.0.0" },
                  { "name": "screening", "schema": "art.compliance.screening_result@^1.0.0" } ]
    }
  ],
  "gateway_variables": [
    { "gateway_id": "Gateway_Repairable",
      "variable": "beneficiary.repair_verdict",
      "source_artifact": "art.payment.repair_verdict" }
  ],
  "policies": {
    "separation_of_duties": [
      { "constraint": "distinct_actor", "elements": ["Task_DraftRepair", "Task_ApproveRepair"] },
      { "constraint": "distinct_actor", "elements": ["Task_DraftReturn", "Task_ApproveReturn"] }
    ]
  },
  "status": "draft"
}
```

**Onboarding validations implied by this contract:** BPMN parses and stays within the supported element subset; every serviceTask/userTask in the BPMN has exactly one binding and vice versa; every `executor.capability` resolves in the capability registry within range; every `schema` ref resolves in the artifact registry; every binding input is produced by some upstream binding output (or is seed state); every `gateway_variables` entry is satisfied; every non-`none` hitl has a role; SoD elements exist in the BPMN. Pass → `validated`; activation pins `resolved` versions → `active`.

---

## 2. Capability descriptor

Registered independently of packs, before any pack can reference it. This is the "capabilities are built first" enforcement point.

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://amendia.dev/schemas/platform/capability-descriptor/1.0.json",
  "title": "CapabilityDescriptor",
  "type": "object",
  "required": ["descriptor_version", "capability_id", "version", "title", "kind",
               "side_effect", "inputs", "outputs", "runtime", "status"],
  "additionalProperties": false,
  "properties": {
    "descriptor_version": { "const": "1.0" },
    "capability_id": { "type": "string", "pattern": "^cap\\.[a-z0-9_]+\\.[a-z0-9_]+$" },
    "version": { "type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+$" },
    "title": { "type": "string" },
    "description": { "type": "string" },
    "kind": {
      "enum": ["skill", "mcp", "llm", "deep_agent"],
      "description": "skill = in-process code (LangGraph subgraph/function); mcp = tools on an MCP server; llm = pure prompt-based step; deep_agent = a bounded LangChain Deep Agents loop inside one node (ADR-021) — nemoclaw-only, HITL-gated, memoized, caged by a tool whitelist + pinned output schema"
    },
    "side_effect": {
      "enum": ["read_only", "side_effectful"],
      "description": "side_effectful = changes state outside Amendia (releases payment, sends messages). Platform policy: side_effectful requires hitl mode >= approve_actions unless a pack explicitly overrides with justification."
    },
    "idempotent": { "type": "boolean", "description": "Safe to retry on failure without an idempotency key" },
    "inputs":  { "type": "array", "items": { "$ref": "#/$defs/io" } },
    "outputs": { "type": "array", "items": { "$ref": "#/$defs/io" } },
    "config_schema": {
      "type": "object",
      "description": "JSON Schema for per-deployment configuration this capability needs (endpoints, list providers, model params). Stored/served by config-forge."
    },
    "runtime": {
      "oneOf": [
        { "type": "object", "required": ["kind", "entrypoint"], "additionalProperties": false,
          "properties": {
            "kind": { "const": "skill" },
            "entrypoint": { "type": "string", "description": "python path, e.g. amendia_caps.payment.enrich:run" } } },
        { "type": "object", "required": ["kind", "server_key", "tools"], "additionalProperties": false,
          "properties": {
            "kind": { "const": "mcp" },
            "server_key": { "type": "string", "description": "Key into config-forge for the MCP server endpoint/auth" },
            "tools": { "type": "array", "items": { "type": "string" }, "minItems": 1 },
            "transport": { "enum": ["streamable_http", "stdio", "sse"], "default": "streamable_http" } } },
        { "type": "object", "required": ["kind", "prompt_key"], "additionalProperties": false,
          "properties": {
            "kind": { "const": "llm" },
            "prompt_key": { "type": "string", "description": "Key into config-forge prompt store" },
            "model_config_key": { "type": "string" },
            "structured_output": { "type": "boolean", "default": true } } }
      ]
    },
    "constraints": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "timeout_seconds": { "type": "integer", "default": 120 },
        "max_retries": { "type": "integer", "default": 2 },
        "min_hitl_mode": {
          "enum": ["none", "review_after", "approve_result", "approve_actions", "manual"],
          "description": "The capability itself can demand a floor; pack bindings may be stricter, never looser."
        }
      }
    },
    "owner": { "type": "string" },
    "status": { "enum": ["active", "deprecated"] },
    "created_at": { "type": "string", "format": "date-time" }
  },
  "$defs": {
    "io": {
      "type": "object",
      "required": ["name", "schema"],
      "additionalProperties": false,
      "properties": {
        "name": { "type": "string" },
        "schema": { "type": "string", "pattern": "^art\\..+@.+$" },
        "required": { "type": "boolean", "default": true }
      }
    }
  }
}
```

### Example

```json
{
  "descriptor_version": "1.0",
  "capability_id": "cap.payment.sanctions_screen",
  "version": "1.0.0",
  "title": "Sanctions & compliance re-screen",
  "kind": "mcp",
  "side_effect": "read_only",
  "idempotent": true,
  "inputs":  [ { "name": "repair", "schema": "art.payment.repair_instruction@^1.0.0" } ],
  "outputs": [ { "name": "screening", "schema": "art.compliance.screening_result@^1.0.0" } ],
  "config_schema": {
    "type": "object",
    "required": ["list_provider"],
    "properties": { "list_provider": { "enum": ["stub", "ofac_sim"] } }
  },
  "runtime": {
    "kind": "mcp",
    "server_key": "mcp.sanctions_screening",
    "tools": ["screen_party"],
    "transport": "streamable_http"
  },
  "constraints": { "timeout_seconds": 60, "max_retries": 1, "min_hitl_mode": "approve_result" },
  "owner": "platform",
  "status": "active"
}
```

---

## 3. Artifact schema registry conventions

Artifacts are the typed objects capabilities read/write in process state; gateways branch on their fields; HITL reviews render them. Each is registered as a JSON Schema under a versioned key.

### Registration envelope — JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://amendia.dev/schemas/platform/artifact-schema-registration/1.0.json",
  "title": "ArtifactSchemaRegistration",
  "type": "object",
  "required": ["artifact_key", "version", "title", "json_schema", "status"],
  "additionalProperties": false,
  "properties": {
    "artifact_key": { "type": "string", "pattern": "^art\\.[a-z0-9_]+\\.[a-z0-9_]+$" },
    "version": { "type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+$" },
    "title": { "type": "string" },
    "description": { "type": "string" },
    "json_schema": {
      "type": "object",
      "description": "A JSON Schema draft 2020-12 document describing artifact instances."
    },
    "compatibility": { "enum": ["backward", "none"], "default": "backward" },
    "tags": { "type": "array", "items": { "type": "string" } },
    "status": { "enum": ["active", "deprecated"] },
    "created_at": { "type": "string", "format": "date-time" }
  }
}
```

### Conventions (enforced by the registry at registration time)

1. `json_schema` must be draft 2020-12, must set its own `$id` to `https://amendia.dev/schemas/artifacts/<domain>/<name>/<version>.json`, must have `"type": "object"` at root, and should set `"additionalProperties": false` (warning if not).
2. Semver semantics: **patch** = descriptions/examples only; **minor** = backward-compatible additions (new *optional* fields, widened enums); **major** = anything breaking (removed/renamed fields, new required fields, narrowed types). With `compatibility: backward`, the registry diff-checks minor/patch submissions against the previous version and rejects breaking ones.
3. Cross-schema reuse via `$ref` to other *registered* schema `$id`s only — no external URLs.
4. The runtime validates every artifact **write** against the pinned schema version at execution time; validation failure fails the task, never silently coerces.
5. Gateway variables (contract 1) are dot-paths into artifacts, so fields referenced by FEEL expressions must be `required` in the schema — checked during pack validation.

### Example — `art.payment.repair_verdict@1.0.0`

```json
{
  "artifact_key": "art.payment.repair_verdict",
  "version": "1.0.0",
  "title": "Beneficiary repairability verdict",
  "json_schema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://amendia.dev/schemas/artifacts/payment/repair_verdict/1.0.0.json",
    "type": "object",
    "required": ["repair_verdict", "confidence", "rationale"],
    "additionalProperties": false,
    "properties": {
      "repair_verdict": { "enum": ["repairable", "unrepairable", "needs_info"] },
      "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
      "rationale": { "type": "string" },
      "proposed_correction": {
        "type": "object",
        "additionalProperties": false,
        "properties": {
          "field": { "type": "string", "description": "e.g. creditor.account.id" },
          "current_value": { "type": "string" },
          "proposed_value": { "type": "string" }
        }
      },
      "evidence": {
        "type": "array",
        "items": {
          "type": "object",
          "required": ["kind", "detail"],
          "properties": {
            "kind": { "enum": ["attachment", "history", "correspondence", "name_match"] },
            "detail": { "type": "string" },
            "attachment_id": { "type": "string" }
          }
        }
      }
    }
  },
  "compatibility": "backward",
  "status": "active"
}
```

(Note `repair_verdict` is a required field — it's the gateway variable `beneficiary.repair_verdict` for `Gateway_Repairable`.)

---

## 4. Dispatch event

Published by the ingestor after triage resolution; consumed by the agent runtime. Marks the ingestion record `dispatched`. The runtime answers with an acceptance event that drives `accepted`/`rejected`.

Routing keys: `ingestor.exception_dispatched.v1` and `agent_runtime.dispatch_accepted.v1` / `agent_runtime.dispatch_rejected.v1`, all on `amendia.events`.

### JSON Schema — `exception_dispatched`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://amendia.dev/schemas/platform/exception-dispatched/1.0.json",
  "title": "ExceptionDispatchedEvent",
  "type": "object",
  "required": ["event_id", "occurred_at", "schema_version",
               "exception_id", "exception_type", "fetch_url", "resolution", "trace"],
  "additionalProperties": false,
  "properties": {
    "event_id": { "type": "string", "format": "uuid" },
    "occurred_at": { "type": "string", "format": "date-time" },
    "schema_version": { "const": "pin.platform.exception_dispatched/1.0" },
    "exception_id": { "type": "string" },
    "exception_type": { "type": "string" },
    "exception_schema_version": { "type": "string", "description": "e.g. pin.payments.wire_exception/1.0" },
    "fetch_url": { "type": "string", "format": "uri",
                   "description": "Where the runtime fetches the full envelope (the source store's fetch-back API)" },
    "resolution": {
      "type": "object",
      "required": ["pack_key", "pack_version", "rule_id"],
      "additionalProperties": false,
      "properties": {
        "pack_key": { "type": "string" },
        "pack_version": { "type": "string", "description": "Exact pinned version, resolved by registry" },
        "rule_id": { "type": "string", "description": "Which triage rule matched" },
        "resolved_at": { "type": "string", "format": "date-time" }
      }
    },
    "trace": {
      "type": "object",
      "required": ["correlation_id"],
      "additionalProperties": false,
      "properties": {
        "correlation_id": { "type": "string",
                            "description": "Stable across the whole exception journey; set to exception_id unless overridden" },
        "causation_id": { "type": "string", "description": "event_id of the exception_raised event that led here" }
      }
    }
  }
}
```

### Acceptance reply — `dispatch_accepted` / `dispatch_rejected`

Same base fields (`event_id`, `occurred_at`, `exception_id`, `trace` with `causation_id` = the dispatch `event_id`), plus:

```json
{
  "schema_version": "pin.platform.dispatch_accepted/1.0",
  "process_instance_id": "PI-7f3a…",
  "pack_key": "wire-repair-standard",
  "pack_version": "1.0.0"
}
```

`dispatch_rejected` replaces `process_instance_id` with `reason` (enum: `unknown_pack`, `pack_not_active`, `fetch_failed`, `envelope_invalid`, `capacity`) and `detail` (string). The ingestor maps these to its `accepted`/`rejected` lifecycle states. Redelivery safety: the runtime treats (`exception_id`, `pack_key`, `pack_version`) as an idempotency key — a duplicate dispatch returns the existing `process_instance_id` in a fresh `dispatch_accepted` rather than starting a second instance.

---

## 5. HITL task / approval model

The single work-item shape behind every human touchpoint (all four non-`none` modes). Created by the runtime when a graph node interrupts; surfaced by the web UI; a decision resumes the graph (`Command(resume=decision)` in LangGraph terms).

### JSON Schema — task document

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://amendia.dev/schemas/platform/hitl-task/1.0.json",
  "title": "HitlTask",
  "type": "object",
  "required": ["task_id", "process_instance_id", "pack_key", "pack_version",
               "element_id", "exception_id", "hitl_mode", "role", "title",
               "payload", "allowed_decisions", "status", "created_at"],
  "additionalProperties": false,
  "properties": {
    "task_id": { "type": "string" },
    "process_instance_id": { "type": "string" },
    "pack_key": { "type": "string" },
    "pack_version": { "type": "string" },
    "element_id": { "type": "string", "description": "BPMN flow node this task belongs to" },
    "exception_id": { "type": "string" },
    "hitl_mode": { "enum": ["review_after", "approve_result", "approve_actions", "manual"] },
    "role": { "type": "string", "pattern": "^role\\." },
    "title": { "type": "string" },
    "description": { "type": "string" },
    "priority": { "enum": ["low", "normal", "high", "critical"], "default": "normal" },
    "due_at": { "type": "string", "format": "date-time" },

    "assignee": { "type": ["string", "null"], "description": "User id once claimed" },
    "sod": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "excluded_users": {
          "type": "array", "items": { "type": "string" },
          "description": "Resolved at task creation from pack SoD policy: actors of the conflicting elements in THIS process instance"
        },
        "derived_from": { "type": "array", "items": { "type": "string" },
                          "description": "element_ids whose actors were excluded" }
      }
    },

    "payload": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "artifacts": {
          "description": "What the human reviews. Each entry is a typed artifact snapshot.",
          "type": "array",
          "items": {
            "type": "object",
            "required": ["name", "schema", "data"],
            "properties": {
              "name": { "type": "string" },
              "schema": { "type": "string", "pattern": "^art\\..+@\\d+\\.\\d+\\.\\d+$" },
              "data": { "type": "object" }
            }
          }
        },
        "proposed_actions": {
          "description": "Only for approve_actions: the side-effectful actions awaiting approval.",
          "type": "array",
          "items": {
            "type": "object",
            "required": ["action_id", "kind", "summary", "detail"],
            "properties": {
              "action_id": { "type": "string" },
              "kind": { "type": "string", "description": "e.g. release_payment, send_pacs004, send_camt029" },
              "summary": { "type": "string" },
              "detail": { "type": "object" }
            }
          }
        },
        "context_url": { "type": "string", "format": "uri",
                         "description": "Deep link into the UI: exception + instance view" }
      }
    },

    "allowed_decisions": {
      "type": "array", "minItems": 1,
      "items": { "enum": ["approve", "reject", "edit_and_approve", "return_for_rework", "complete", "escalate"] }
    },

    "status": { "enum": ["open", "claimed", "decided", "cancelled", "expired"] },
    "decision": {
      "type": "object",
      "required": ["decision", "decided_by", "decided_at"],
      "additionalProperties": false,
      "properties": {
        "decision": { "enum": ["approve", "reject", "edit_and_approve", "return_for_rework", "complete", "escalate"] },
        "decided_by": { "type": "string" },
        "decided_at": { "type": "string", "format": "date-time" },
        "comment": { "type": "string" },
        "edits": {
          "type": "object",
          "description": "For edit_and_approve: full replacement artifact data, re-validated against the artifact schema before resume."
        },
        "approved_action_ids": {
          "type": "array", "items": { "type": "string" },
          "description": "For approve_actions with partial approval; absent = all"
        }
      }
    },
    "created_at": { "type": "string", "format": "date-time" },
    "updated_at": { "type": "string", "format": "date-time" }
  }
}
```

### Semantics

Mode → default `allowed_decisions`: `review_after` → approve, edit_and_approve, reject; `approve_result` → approve, reject; `approve_actions` → approve, reject (optionally partial via `approved_action_ids`); `manual` → complete, escalate (with an artifact form defined by the binding's outputs).

Lifecycle: `open → claimed → decided`, with `cancelled` (instance terminated) and `expired` (past `due_at`; runtime policy decides escalation). Claim enforcement: claimant must hold `role` and not be in `sod.excluded_users` — checked at claim AND at decide.

Decision → runtime mapping: `approve`/`complete` resume the graph forward; `edit_and_approve` validates `edits` against the pinned artifact schema, replaces the artifact in state, resumes; `reject` on `review_after`/`approve_result` re-runs or routes per binding policy (v1: re-run capability once, then escalate); `reject` on `approve_actions` means actions are NOT executed and the graph takes the pack-defined rejection path; `return_for_rework` resumes backward to the producing node.

Events (on `amendia.events`): `agent_runtime.hitl_task_created.v1` and `…hitl_task_decided.v1`, thin payloads (`task_id`, `exception_id`, `process_instance_id`, `element_id`, `role`, and for decided: `decision`, `decided_by`) — this is what the notification service fans out to the UI.

Audit: the task document is immutable after `decided` except `updated_at`; together with the runtime's checkpoints, (task, decision, checkpoint-before, checkpoint-after) forms the four-eyes audit record.

---

## Cross-contract validation summary (what makes onboarding "well defined")

| Check | Contracts involved |
|---|---|
| Every BPMN task ↔ exactly one binding | 1 ↔ BPMN |
| Binding capability exists, version in range, status active | 1 → 2 |
| Binding hitl mode ≥ capability `min_hitl_mode`; side_effectful ⇒ ≥ approve_actions | 1 → 2 |
| **deep_agent** (ADR-021): bound behind a HITL gate (≠ none); `read_only` unless `deep_agent_justifications` provided; every `tools[]` resolves; pack marked nemoclaw-required | 1 → 2 |
| Binding input/output schemas ≡ capability declared IO schemas (compatible versions) | 1 → 2 → 3 |
| Every artifact ref registered & active; gateway variables are required fields | 1 → 3 |
| Dispatch resolution pins pack version that is `active` | 4 → 1 |
| HITL task payload artifacts validate against pinned schemas; SoD resolved from pack policy | 5 → 1, 3 |

Open items deliberately deferred: timer/escalation events (BPMN subset v2), compensation, capability config resolution order (config-forge design), and the `manual` task artifact form-rendering hints (UI scope).
