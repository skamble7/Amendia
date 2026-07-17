# Amendia — BPMN Conformance Recon Dossier

> **Read-only reconnaissance** for the three-phase BPMN-conformance work (Phase 0 reject→classify,
> Phase 1 full-BPMN importer + inference, Phase 2 grow toward the BPMN Common Executable sub-class).
> No code was modified in producing this. Every claim cites exact paths + line ranges. Compiled
> 2026-07-16.

Contents: 1) Repo topography & tooling · 2) `libs/amendia_bpmn` reject→classify surface ·
3) process-registry validation & onboarding strictness · 4) OnboardingSession (Phase-1 inference
targets) · 5) `libs/amendia_contracts` (models inference must produce) · 6) agent-runtime engine
(Phase-2 build-vs-buy inputs) · 7) webui wizard & BPMN rendering · 8) openspec/ & ADR conventions ·
Final synthesis.

---

## 1. Repo topography & tooling

**Top-level layout** (`/Users/sandeep/Documents/Projects/Amendia`, root `ls`):
- `backend/` — present. Contains `services/`, `docs/`, `deploy/`.
- `libs/` — present.
- `webui/` — present.
- `deploy/` — present (root-level; separate from `backend/deploy/`). Holds `helm/` and `vault/`.
- `openspec/` — present.
- `stub_exception_generator/` — present (has its own `uv.lock` + `pyproject.toml`).
- `tools/` — present; single file `demo_wire_repair.sh` (a demo shell script, not a build-tool dir).
- `mcp_stub/` — present and notable: standalone deterministic MCP servers, explicitly "not Amendia
  services… a sibling of `backend/`, `webui/`, `libs/`, `deploy/`" (`mcp_stub/README.md:1-15`).
  Contains `servers/`, `deploy/`, `README.md`.
- Also at root: `README.md`, `.claude/`. **Confirmed absence: no root `pyproject.toml`** (no top-level
  uv/poetry workspace).

**`libs/` packages** (5 package dirs plus one aggregate pyproject): `amendia_auth`, `amendia_bpmn`,
`amendia_common`, `amendia_contracts`, `polyllm`. `libs/pyproject.toml:5-13` declares the package
`amendia-common` (packages `["amendia_common"]`) — i.e. `libs/` root itself *is* the `amendia-common`
distribution; the other four are nested distributions.

**Python — package manager & wiring:**
- Manager is **uv**. No `poetry.lock`, no `requirements*.txt`; `uv.lock` files exist per-service:
  `backend/services/{ingestor,process-registry,agent-runtime}/uv.lock` and
  `stub_exception_generator/uv.lock`. The platform trio (identity/notification/config-forge) carry no
  lock.
- Libs are wired as **editable path deps** via `[tool.uv.sources]`. Example
  (`backend/services/agent-runtime/pyproject.toml:44-49`):
  `amendia-common = { path = "../../../libs", editable = true }`, plus `amendia-contracts`,
  `amendia-bpmn`, `amendia-auth`, `polyllm` all `editable = true`. Platform services under
  `backend/services/platform/*` use a 4-level `../../../../libs` path (e.g. `identity/pyproject.toml:33-36`).
  Tests also inject libs onto `pythonpath` in `[tool.pytest.ini_options]` (`agent-runtime/pyproject.toml:55`).
- **Run one service's tests** (`agent-runtime/README.md:103-109`): `cd backend/services/agent-runtime`
  → `uv pip install -e '.[dev]'` → `pytest`. Per-service venvs exist at
  `backend/services/{agent-runtime,ingestor,process-registry}/.venv`, `libs/amendia_auth/.venv`,
  `stub_exception_generator/.venv`. Pytest config: `asyncio_mode = "auto"`, `addopts = "-q"`
  (`agent-runtime/pyproject.toml:54-60`).
- **Python version** — no `.python-version` anywhere (confirmed absent). Set via `requires-python`:
  agent-runtime / ingestor / process-registry = `>=3.12`; platform identity/notification/config-forge =
  `>=3.11`; `libs/pyproject.toml:9` = `>=3.11`; `mcp_stub/.../pyproject.toml:9` = `>=3.11`.

**Node / webui** (`webui/package.json`):
- Manager is **npm** — lockfile `webui/package-lock.json` present; no pnpm/yarn lock.
- Build: `"build": "tsc --noEmit && vite build"` (`:8`). Test: `"test": "vitest run"` / `"test:watch":
  "vitest"` (`:11-12`). Also `dev` (vite), `lint`, `gen:api` / `gen:api:check` (OpenAPI typegen) (`:7-14`).

**Exact pinned versions** (quoted):
- `langgraph` — `"langgraph>=0.2.0",` (`agent-runtime/pyproject.toml:22`). Only agent-runtime declares it.
  (venv actually resolves **langgraph 0.4.6** — see §6.)
- `langgraph-checkpoint-mongodb` — `"langgraph-checkpoint-mongodb>=0.1.0",` (`agent-runtime/pyproject.toml:23`).
- `pydantic` — `"pydantic>=2.7",` (uniform across all backend services; also `libs/polyllm`).
- `fastapi` — `"fastapi>=0.115",` (all six backend services).
- `mcp` — `"mcp>=1.2",` (`process-registry/pyproject.toml:21`, only backend consumer; "lazy-imported;
  fake injected in tests"). Separately `"mcp>=1.9",` in `mcp_stub/servers/wire_transfer_exception/pyproject.toml:11`.
- webui BPMN deps — `"bpmn-js": "^17.11.1",` (`webui/package.json:28`). **`bpmn-moddle` confirmed absent** —
  no `bpmn-moddle` entry and no other `bpmn`-named dependency.

**Seam:** `[tool.uv.sources]` editable path deps (relative `../../../libs`) bind every backend service to
the shared `libs/` packages; a lib change is picked up without republish.
**Risk:** No root workspace/lockfile; per-service `uv.lock` on only 3 of 6 backend services (platform trio
unlocked) → dependency versions can drift despite identical `>=` floors; relative-path depth differs
(`../../../` vs `../../../../`), so moving a service breaks resolution.

---

## 2. `libs/amendia_bpmn` — the reject→classify surface (Phase 0 core)

**Package file list** (`libs/amendia_bpmn/`)

| Path | Role |
|---|---|
| `amendia_bpmn/__init__.py` (L1–19) | Public surface. Re-exports `BpmnModel, Finding, Flow, compute_sha256, local_name, parse`; `__all__` = those six. |
| `amendia_bpmn/model.py` (L1–68) | Dataclasses (`Finding`, `Flow`, `BpmnModel`) + the Iteration-1 element-subset constants + `local_name`/`compute_sha256`. |
| `amendia_bpmn/parser.py` (L1–183) | `parse(xml, expected_process_id)` — ElementTree parse, subset gate, all structural findings. Private `_bfs`. |
| `pyproject.toml` | Package metadata only. |

**Confirmed absence:** **no `tests/` directory inside `libs/amendia_bpmn`** — behavior is exercised only
from the two consuming services' suites (see below).

### `model.py` — element-kind constants (exact values, L17–21)

```python
TASK_KINDS = {"serviceTask", "userTask"}                          # L17
GATEWAY_KINDS = {"exclusiveGateway", "parallelGateway"}           # L18
EVENT_KINDS = {"startEvent", "endEvent"}                          # L19
NODE_KINDS = TASK_KINDS | GATEWAY_KINDS | EVENT_KINDS             # L20
IGNORE_CHILDREN = {"documentation", "extensionElements", "incoming", "outgoing"}  # L21
```
Also `BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"` (L15). No other kind constants exist.

- **`Finding` dataclass (L32–38):** `code: str`, `message: str`, `element_id: Optional[str] = None`.
  **No severity field.** Docstring L34: *"Neutral, framework-agnostic parse finding (severity is always
  error here)."*
- **`Flow` dataclass (L41–48):** `id`, `source`, `target`, `has_condition: bool`,
  `condition_expr: Optional[str] = None` (raw `<conditionExpression>` text, for the runtime compiler),
  `name: Optional[str] = None`.
- **`BpmnModel` dataclass (L51–67):** `process_id: str`; `tasks: Dict[str,str]` (id→`serviceTask|userTask`);
  `exclusive_gateways: List[str]`; `parallel_gateways: List[str]`; `node_ids: Set[str]`; `flows: List[Flow]`;
  `exclusive_conditions: Dict[str,List[str]]`; `start_events: List[str]`; `end_events: List[str]`;
  `gateway_defaults: Dict[str,str]`. Method `outgoing(node_id)` (L66–67).

### `parser.py` — supported vs unsupported (L56–90) + the retention question

The parser iterates the matched `<process>`'s direct children (L56), skips `IGNORE_CHILDREN` (L58–59),
handles `sequenceFlow` (L61–70), and gates on `if name in NODE_KINDS:` (L71–84). The sole "unsupported"
path is the `else` (L85–90):

```python
else:
    findings.append(Finding(
        "bpmn_unsupported_element",
        f"unsupported BPMN element '{name}'" + (f" (id={node_id})" if node_id else ""),
        element_id=node_id,
    ))                                                    # parser.py L85–90
```

**CRITICAL — are unknown elements retained anywhere? No — they are discarded.** The `else` branch records
only a `Finding`; the element is **not** added to `node_ids`, `tasks`, `flows`, or any other collection.
There is **no** `unsupported`/`unknown`/`extra` field on `BpmnModel` (field list L52–64 — every field is a
typed collection of *recognized* nodes/flows). The element's `id` survives only as `Finding.element_id`
(and only if it had an `id`). Downstream, the unsupported element is unrecoverable from the model.

**Every structural check + finding `code`:**

| `code` | Where | Trigger |
|---|---|---|
| `bpmn_parse_error` | L41 | `ET.fromstring` raises `ParseError` → returns `(None, [finding])` |
| `bpmn_process_not_found` | L47–51 | no `<process>` matches `expected_process_id` → returns `(None, …)` |
| `bpmn_unsupported_element` | L86–90 | element kind not in `NODE_KINDS`/`sequenceFlow`/`IGNORE_CHILDREN` |
| `bpmn_dangling_flow` | L95–99 (src) & L100–105 (tgt) | `sourceRef`/`targetRef` not a known node id |
| `bpmn_start_event_count` | L108–112 | `len(start_events) != 1` |
| `bpmn_no_end_event` | L113–114 | `end_events` empty |
| `bpmn_unreachable_node` | L126–131 | node not reachable forward from start (`_bfs` on `adj`) |
| `bpmn_no_path_to_end` | L136–141 | node cannot reach any end (`_bfs` on reverse adj) |
| `bpmn_conditionless_exclusive_flow` | L151–156 | exclusive outgoing flow with no condition, not the `default` |
| `bpmn_parallel_flow_condition` | L162–168 | parallel outgoing flow that carries a condition |

`bpmn_sha_mismatch` and `bpmn_missing` are **not** in the lib (registry-side; see §3).

**Severity concept in the lib: none.** `Finding` has no severity; docstrings state severity "is always
error here" (`model.py:34`) and "error-level `Finding` objects" (`parser.py:33-34`). Every finding is
implicitly an error; warning/info exist only after the registry adapter maps them (§3).

**Every caller of `amendia_bpmn`:**
1. **process-registry `app/validation/bpmn.py:14`** — `from amendia_bpmn import BpmnModel, Flow,
   compute_sha256, parse`. Uses `compute_sha256(xml)` (L33), `parse(xml, expected_process_id)` (L38), maps
   each `Finding` via `f.code`/`f.element_id`/`f.message` (L39–40).
2. **process-registry `app/services/onboarding.py:18`** — `from amendia_bpmn.parser import parse as
   parse_bpmn`. In `_parse_and_check_bpmn` (L617) uses `model.exclusive_gateways`, `parallel_gateways`,
   `flows` (`.source`/`.target`), `tasks`; reads `f.code`/`element_id`/`message` (L618).
3. **agent-runtime `app/engine/bundle.py:16`** — `from amendia_bpmn import BpmnModel, parse`; stores
   `bpmn_model` (L32); `parse(...)` (L63); rejects on `[f.code for f in findings]` (L65).
4. **agent-runtime `app/engine/engine.py:34`** — `from amendia_bpmn import parse`; `parse(...)` (L123),
   rejects on codes (L125).
5. **agent-runtime `app/engine/compiler.py`** (consumes the `BpmnModel`) — `parallel_gateways` (L42–44),
   `start_events` (L47–48, L80), `tasks` (L51), `end_events` (L52, L65), `exclusive_gateways` (L53),
   `outgoing(...)` (L80, L87, L118), `gateway_defaults` (L119), per-flow `condition_expr` (L130, 136, 139).
6. **agent-runtime `tests/test_compiler.py:10`** — `from amendia_bpmn import parse`.

**Tests:** `process-registry/tests/test_bpmn.py` (via adapter): `test_minimal_valid_passes`,
`test_seed_bpmn_passes_stage1`, `test_sha_mismatch`, `test_process_not_found_returns_none`,
`test_unsupported_element` (uses `<boundaryEvent>`), `test_unreachable_node`,
`test_conditionless_exclusive_flow`. Not asserted here: `bpmn_dangling_flow`, `bpmn_no_end_event`,
`bpmn_start_event_count`, `bpmn_no_path_to_end`, `bpmn_parallel_flow_condition`.
`agent-runtime/tests/test_compiler.py`: `test_seed_bundle_compiles`, `test_compilation_is_deterministic`,
`test_gateway_routing_table`, `test_parallel_gateway_rejected`, `test_unparseable_condition_rejected`,
`test_unsupported_element_reported_by_parser`.

**Seam:** the lib is the single source of truth for the element subset; its neutral `Finding`
(code/message/element_id, no severity) is the exact contract the registry adapter (`bpmn.py:39-40`) and
the agent-runtime rejection paths (`bundle.py:65`, `engine.py:125`) consume by `code`.
**Risk:** unsupported elements are dropped, not retained — the model carries no record beyond a message
string, so any "show me what you couldn't classify" UX cannot round-trip element ids for elements lacking
an `id`, and reachability/bijection stages silently operate on a model with holes where the unsupported
node sat.

---

## 3. process-registry validation & onboarding strictness

**`ValidationReport` / `Finding` live in `app/validation/report.py`** (not `models/registry.py`).

- **`Severity` enum (L14–17):** `ERROR="error"`, `WARNING="warning"`, `INFO="info"` — severities **do**
  exist here (unlike the lib).
- **`Finding` (BaseModel, L20–26):** `code`, `severity: Severity`, `message`, `stage: int = 0`,
  `element_id: Optional[str]`, `path: Optional[str]`.
- **`ValidationReport` (L29–77):** `pack_key`, `pack_version`, `findings: List[Finding]`, `created_at`.
  Builders `add/error/warning/info` (L36–60). Queries:

```python
@property
def has_errors(self) -> bool:
    return any(f.severity is Severity.ERROR for f in self.findings)   # L64–65
@property
def ok(self) -> bool:
    return not self.has_errors                                         # L68–69
def error_codes(self) -> List[str]:
    return [f.code for f in self.findings if f.severity is Severity.ERROR]  # L71–72
```

**Warnings do NOT affect `ok`.** `ok = not has_errors`, and `has_errors` counts only `Severity.ERROR`.
WARNING/INFO never flip `ok` or appear in `error_codes()`. `finalize()` (L74–77) sorts findings by
`(stage, element_id, code, path)`.

**`PackValidator` — seven stages** (`app/validation/pack_validator.py`, `validate()` L50–81):
1. **Stage 1 — BPMN** `_stage1_bpmn` (L86–97). `bpmn_missing` (L90) if no XML; else delegates to
   `parse_and_validate`.
2. **Stage 2 — binding↔task bijection** `_stage2_bijection` (L102–127). `duplicate_binding`,
   `orphan_binding`, `binding_kind_mismatch`, `executor_kind_mismatch`, `unbound_task`; `stage_skipped`
   (L66) if no model.
3. **Stage 3 — capability resolution** `_stage3_capabilities` (L145–180). `unknown_capability`,
   `capability_no_version_in_range`, `capability_only_deprecated`, plus `capability_not_declared`
   (**warning**, L172/177).
4. **Stage 4 — HITL & side-effect policy** `_stage4_hitl_policy` (L185–208). `hitl_role_missing`,
   `side_effect_requires_approve_actions`, `hitl_below_capability_floor`; then
   `validate_deep_agent_bindings` (L208).
5. **Stage 5 — artifacts & IO** `_stage5_artifacts_io` (L244–296). `unknown_artifact_schema`,
   `artifact_no_version_in_range`, `artifact_only_deprecated`, `binding_io_mismatch`,
   `binding_io_schema_incompatible`, plus `unproduced_input` (**warning**, L294); `stage_skipped` (L73).
6. **Stage 6 — gateway variables** `_stage6_gateway_vars` (L321–364). `gateway_variable_unknown_gateway`,
   `gateway_variable_unproduced`, `gateway_variable_schema_missing`, `gateway_variable_not_required`, plus
   `gateway_without_variable` (**warning**, L331); `stage_skipped` (L78).
7. **Stage 7 — policies & triage** `_stage7_policies_triage` (L369–400). `sod_too_few_elements`,
   `sod_unknown_element`, `triage_rule_invalid`, plus `triage_rule_smoke` (**info**, L396).

**How `amendia_bpmn` findings fold in — Stage 1 only**, via `app/validation/bpmn.py::parse_and_validate`
(L23–41). It first runs the manifest-coupled sha check (`bpmn_sha_mismatch`, L32–36 — *this code exists
only here*), then:

```python
model, findings = parse(xml, expected_process_id)
for f in findings:
    report.error(f.code, stage=STAGE, element_id=f.element_id, message=f.message)  # bpmn.py L38–40
```

Every neutral lib `Finding` is mapped **1:1 as `Severity.ERROR` at `stage=1`** (`STAGE=1`, L18). So all 10
lib codes surface as errors, plus `bpmn_sha_mismatch` (adapter) and `bpmn_missing` (validator L90).

**`onboarding.py::_parse_and_check_bpmn` (L609–644) — onboarding-strict EXTRA checks.** After running the
same shared `parse_bpmn` (L617) it adds (L622–632):

```python
gateways = set(model.exclusive_gateways) | set(getattr(model, "parallel_gateways", []))
for pg in getattr(model, "parallel_gateways", []):
    errs.append({"code": "bpmn_parallel_gateway_unsupported", "element_id": pg,
                 "message": "parallel gateways are not supported; use exclusive (XOR) gateways only"})
for flow in model.flows:
    if flow.source in gateways and flow.target in gateways:
        errs.append({"code": "bpmn_chained_gateway_unsupported", "element_id": flow.source,
                     "message": f"gateway '{flow.source}' flows directly into gateway '{flow.target}'; "
                                f"chained gateways are not supported"})   # L624–632
```

- **`bpmn_parallel_gateway_unsupported`** (L626) — onboarding forbids `parallelGateway` entirely even
  though the shared parser *accepts* it. Enforced at `onboarding.py:625-627`.
- **`bpmn_chained_gateway_unsupported`** (L630) — any gateway→gateway flow. Enforced at `onboarding.py:628-632`.

Both are onboarding-local dict findings, not `Severity` objects. **Divergence:** onboarding's
`_extract_process_id` (L650–659) prefers a `<process>` with `isExecutable="true"`, whereas the shared
parser matches purely on `expected_process_id` (`parser.py:44-45`).

**Endpoints touching BPMN + 422 shape:**
- **`PUT /packs/{k}/{v}/bpmn`** — `packs.py::upload_bpmn` (L65–83) does **not** parse/validate; only status
  check + store XML/sha. Empty body → `HTTPException(422, "empty BPMN body")` (L77–78). Structural
  validation happens later via `POST /packs/{k}/{v}/validate` (L86–100), which returns the full
  `ValidationReport` as the 200 body — it does not 422 on findings.
- **`PUT /onboarding/{id}/bpmn`** — router `attach_bpmn` (L114–123) → service `attach_bpmn` (L207–232). The
  422 the wizard renders (service L215): `raise TransitionError(422, {"error": "bpmn_invalid", "findings":
  inv_errors})`. The router's `_raise` re-raises as `HTTPException(detail=exc.detail)`, so the wizard body
  is `{"detail": {"error":"bpmn_invalid","findings":[{"code","element_id","message"}, …]}}` — shared-parser
  codes plus the two extra onboarding codes, flattened into one `findings` array (distinct from the
  `ValidationReport` JSON of `POST .../validate`).

**Seam:** two BPMN entry paths share `amendia_bpmn.parse` but diverge in wrapping — the pack path funnels
lib findings into a `ValidationReport` (Stage-1 errors, sha check, `error_codes()` gate); the onboarding
path wraps them into a flat `{"error":"bpmn_invalid","findings":[…]}` 422 and layers two extra strictness
codes.
**Risk:** onboarding and the canonical `PackValidator` can disagree — onboarding rejects
parallel/chained gateways the pack-side `validate`/`activate` path would accept, and the two paths select
the `<process>` differently (`isExecutable` preference vs exact id). Warnings
(`capability_not_declared`, `unproduced_input`, `gateway_without_variable`) never block `ok`/activation.

---

## 4. OnboardingSession — models, repo, router (Phase-1 inference targets)

### 4.1 `app/models/onboarding.py` — model inventory

| Category | Model names (line) |
|---|---|
| State machine | `OnboardingState` (27–39), `_STATE_ORDER` (43–52), `state_rank()` (55–56) |
| Staged sub-docs | `Basics` (63), `BpmnInventory` (71), `StagedArtifact` (83), `StagedCapability` (95), `StagedBindingIO` (121), `StagedBinding` (127), `StagedTriageRule` (140), `StagedGatewayVariable` (147), `StagedSod` (153), `RoleMeta` (157), `CommitStep` (164) |
| Aggregate | `OnboardingSession` (175) |
| Request bodies | `CreateSessionRequest` (212), `AttachBpmnRequest` (220), `CapabilityToolSelection` (225), `SetCapabilitiesRequest` (250), `BindingInput` (255), `SetBindingsRequest` (266), `SetTriageRequest` (270), `SetPoliciesRequest` (274) |
| MCP introspect | `IntrospectMcpRequest` (285), `ToolCompliance` (292), `IntrospectedTool` (297), `IntrospectMcpResponse` (309) |

Module docstring (L6–10): staged models use **permissive `pydantic.BaseModel`**, NOT strict
`ContractModel`; the strict contract models are composed only at *assemble* time.

**`OnboardingState` (L27–39):** `INITIATED → BPMN_ATTACHED → CAPABILITIES_RESOLVED → BINDINGS_SET →
TRIAGE_SET → POLICIES_SET → ASSEMBLED → COMPLETED`. `_STATE_ORDER` fixes this ordering for "at least state
X" guards; `state_rank()` returns the index.

**`Basics` (L63–68):** `pack_key`, `version`, `title`, `description: Optional=None`,
`default_domain: str = "payment"`.

**`BpmnInventory` — what BPMN parse captures today (L71–80):**
```
process_id: str
bpmn_file: str
sha256: str
service_tasks: List[str]           # ids
user_tasks: List[str]              # ids
gateways: List[str]                # exclusive gateways only
task_names: Dict[str, str]         # id -> human name (best effort)
```
**Confirmed absences:** it does NOT capture sequence flows/edges, gateway branch conditions,
gateway→target topology, data objects, lanes/pools, or any element type beyond
serviceTask/userTask/exclusiveGateway.

**Staged models (field lists):**
- `StagedArtifact` (83–92): `artifact_key`, `version`, `title`, `description?`, `json_schema: Dict`,
  `compatibility: str = "backward"`, `source_tool?`.
- `StagedCapability` (95–118): `capability_id`, `version`, `title`, `description?`,
  `side_effect: str = "read_only"`, `idempotent: Optional[bool]`, `min_hitl_mode: Optional[str]`,
  `input_name`, `input_artifact_key`, `output_name`, `output_artifact_key`, `endpoint`, `tool`,
  `transport: str = "streamable_http"`, `headers: Dict`, `source_tool?`.
- `StagedBindingIO` (121–124): `name`, `schema_ref: str` (`art.<...>@<range>`), `required: bool = True`.
- `StagedBinding` (127–137): `element_id`, `element_kind: str`, `executor_type: str`,
  `capability_ref?`, `role?`, `assist_capability_ref?`, `hitl_mode: str = "none"`, `hitl_role?`,
  `inputs: List[StagedBindingIO]`, `outputs: List[StagedBindingIO]`.
- `StagedTriageRule` (140–144): `rule_id`, `priority: int = 100`, `description?`, `when: Dict` (predicate
  tree).
- `StagedGatewayVariable` (147–150): `gateway_id`, `variable`, `source_artifact` (bare `art.<...>`).
- `StagedSod` (153–154): `elements: List[str]`.
- `RoleMeta` (157–161): `label?`, `description?`.
- `CommitStep` (164–168): `key`, `label`, `status: str = "pending"`, `detail?`.

**`OnboardingSession` aggregate (L175–205):** `session_id`, `created_by`, `created_at`, `updated_at`,
`state`, `basics: Basics`, `bpmn: Optional[BpmnInventory]`, `staged_artifacts`, `staged_capabilities`,
`reused_capability_refs`, `bindings`, `triage_rules`, `gateway_variables`, `sod_policies`, `roles`,
`role_meta: Dict[str, RoleMeta]`, `dry_run_report: Optional[Dict]`, `commit_progress`, `result_pack?`,
`last_cleared: List[str]`. Helpers `to_doc()` (→ `model_dump(mode="json")`) and `at_least(state)`.

### 4.2 `app/services/mcp_introspect.py` — the inference template Phase-1 mirrors

- **`sanitize_name(raw) -> str`** (125–128): `re.sub(r"[^a-z0-9_]+","_",raw.lower()).strip("_")`, fallback
  `"tool"`.
- **`suggest_ids(tool_name, domain) -> Dict`** (205–211): `input_artifact_key = f"art.{domain}.{name}_input"`,
  `output_artifact_key = f"art.{domain}.{name}_output"`, `capability_id = f"cap.{domain}.{name}"`
  (`name = sanitize_name(tool_name)`).
- **`evaluate_compliance(tool) -> ToolCompliance`** (159–177): non-compliant if `output_schema is None`, a
  schema is not a dict, root `type` not in `(None,"object")`, or any external `$ref`
  (`_is_external_ref`: absolute non-amendia.dev URL or bare relative; local `#/...` allowed).
- **`normalize_artifact_schema(raw, *, artifact_key, version) -> (schema, warnings)`** (180–202): deep-copy;
  force `$schema=draft-2020-12`, `type="object"`, `$id=canonical_artifact_id(...)`
  (`https://amendia.dev/schemas/artifacts/{domain}/{name}/{version}.json`); default
  `additionalProperties:false` (+warn) if absent; **raise `ValueError`** on any external `$ref`.
- **`introspect_response_tool(tool, *, domain) -> IntrospectedTool`** (214–227): compliance verdict +
  `suggest_ids` (only if compliant) + schemas.
- **`infer_capability(*, tool, endpoint, transport, headers, domain, input_schema, output_schema,
  input_artifact_key, output_artifact_key, capability_id, artifact_version, capability_version,
  side_effect, idempotent, min_hitl_mode, title, description) -> (StagedArtifact, StagedArtifact,
  StagedCapability, List[str])`** (230–288): re-runs compliance (raises if non-compliant), builds two
  `StagedArtifact`s (`source_tool=tool`) + one `StagedCapability` wiring endpoint/tool/transport/headers.

Supporting internals: `RawMcpTool` (45–50), `McpIntrospector` Protocol (53–59), `RealMcpIntrospector`
(66–118, 12s timeout, lazy `mcp` import), `canonical_artifact_id` (131–133), `_collect_refs`/
`_is_external_ref` (136–156), `_AMENDIA_ID_RE` (36–38).

### 4.3 `app/routers/onboarding.py` — endpoints + DI

Two routers: `router` (`prefix="/onboarding"`) + `introspect_router` (`prefix="/capabilities"`, L33).
Every route depends on `_owner_id` (38–39) wrapping `require_roles("role.process.owner")` → owner-scoped.
Service injected via `Depends(get_onboarding_service)` (L17). `TransitionError` → `HTTPException` via
`_raise` (42–43).

| Method + path | Handler | response_model |
|---|---|---|
| POST `/capabilities/introspect-mcp` | `introspect_mcp` (50) | `IntrospectMcpResponse` |
| POST `/onboarding` (201) | `create_session` (66) | `OnboardingSession` |
| GET `/onboarding` | `list_sessions` (78) | `List[OnboardingSession]` |
| GET `/onboarding/{id}` | `get_session` (86) | `OnboardingSession` |
| DELETE `/onboarding/{id}` (204) | `delete_session` (98) | — |
| PUT `/onboarding/{id}/bpmn` | `attach_bpmn` (114) | `OnboardingSession` |
| POST `/onboarding/{id}/capabilities` | `set_capabilities` (126) | `OnboardingSession` |
| PUT `/onboarding/{id}/bindings` | `set_bindings` (138) | `OnboardingSession` |
| PUT `/onboarding/{id}/triage` | `set_triage` (150) | `OnboardingSession` |
| PUT `/onboarding/{id}/policies` | `set_policies` (162) | `OnboardingSession` |
| POST `/onboarding/{id}/assemble` | `assemble` (174) | `OnboardingSession` |
| POST `/onboarding/{id}/commit` | `commit` (186) | `OnboardingSession` |

**Wizard state → frontend:** every transition endpoint declares `response_model=OnboardingSession` and
returns the full serialized aggregate (docstring L2–5: "Each transition returns the full updated session so
the webui can render it"). Only `introspect-mcp` and `delete` differ.

**Seam:** the mirror point for Phase-1 inference is `mcp_introspect.infer_capability`/`suggest_ids`/
`normalize_artifact_schema`; injection seam is `get_onboarding_service` + the `McpIntrospector` Protocol.
Phase-1 output must land as the same permissive staged models on the session, round-tripped whole to the UI.
**Risk:** (1) `BpmnInventory` is topology-thin — Phase-1 inference of triage/gateway-variables from BPMN
structure has almost nothing to consume beyond ids + names. (2) Staged models are permissive (free-form
`str` for `side_effect`/`hitl_mode`/`element_kind`/refs) — bad inference isn't caught until assemble. (3)
`introspect-mcp` connects to an operator-supplied URL — SSRF surface, mitigated only by owner-gating + 12s
timeout.

---

## 5. `libs/amendia_contracts` — the models inference must produce

### 5.1 `process_pack.py` — `ProcessPackManifest` + nested models

`ProcessPackManifest` (174–192), base `ContractModel, TimestampsMixin`:
```
manifest_version: Literal["1.0"]
pack_key: PackKey
version: SemVerStr
title: str
description: Optional[str] = None
process: ProcessRef
triage_rules: List[TriageRule] = Field(..., min_length=1)
requires_capabilities: List[RequiresCapability]
artifacts: List[ArtifactRef]
bindings: List[Binding] = Field(..., min_length=1)
gateway_variables: Optional[List[GatewayVariable]] = None
policies: Optional[Policies] = None
deep_agent_justifications: Dict[str, str] = Field(default_factory=dict)   # ADR-021
status: PackStatus
created_by: Optional[str] = None
```
**REQUIRED (block a partial draft):** `manifest_version` (exactly `"1.0"`), `pack_key`, `version`, `title`,
`process`, `triage_rules` (**min_length=1**), `requires_capabilities`, `artifacts`, `bindings`
(**min_length=1**), `status`. Optional/defaulted: `description`, `gateway_variables`, `policies`,
`deep_agent_justifications` (`{}`), `created_by`, timestamps.

Nested models:
- `ProcessRef` (128–131): `bpmn_file`, `process_id`, `bpmn_sha256: Sha256Hex`.
- `TriageRule` (73–77): `rule_id`, `priority: int` (REQUIRED), `description?`, `when: Predicate`.
- **`Predicate`** recursive tagged union (66): `Union[AllPredicate, AnyPredicate, NotPredicate,
  LeafPredicate]` — `AllPredicate.all` / `AnyPredicate.any` (each `List["Predicate"]`, min_length=1),
  `NotPredicate.not_` (alias `"not"`), `LeafPredicate {field, op: LeafOp, value}`. `LeafOp` (32–43):
  `eq, ne, in, starts_with, intersects, exists, gt, gte, lt, lte`. Each branch `extra="forbid"`;
  present key selects member.
- **`Executor`** union (95): `Union[CapabilityExecutor, HumanExecutor]`, `discriminator="type"`.
  `CapabilityExecutor {type:"capability", capability: CapabilityRef}`;
  `HumanExecutor {type:"human", role: RoleId, assist_capability?: CapabilityRef}`.
- `Hitl` (98–106): `mode: HitlMode`, `role: Optional[RoleId]`. `@model_validator`
  **`_role_required_unless_none`** — raises if `mode != NONE and role is None`.
- `ArtifactIO` (109–113): `name`, `schema_: ArtifactRef` (alias `"schema"`), `required: bool = True`.
- `Binding` (115–121): `element_id`, `element_kind: Literal["serviceTask","userTask"]`,
  `executor: Executor` (discriminated), `hitl: Hitl` (**REQUIRED**), `inputs`/`outputs: List[ArtifactIO]`.
- `RequiresCapability` (134–145): `ref: CapabilityRef`, `resolved: Optional[CapabilityRef]`.
  `@field_validator` **`_resolved_must_be_pinned`** — if set, must be `is_pinned` (exact semver).
- `GatewayVariable` (148–151): `gateway_id`, `variable`, `source_artifact: ArtifactBareRef`.
- `Policies` (159–160): `separation_of_duties: Optional[List[SeparationOfDuties]]`;
  `SeparationOfDuties` (154–157): `constraint: Literal["distinct_actor"]`, `elements: List[str]`
  (**min_length=2**).
- `PackStatus` (163–167): `draft, validated, active, deprecated`.

**Strictness:** every model subclasses `ContractModel`, whose `model_config =
ConfigDict(extra="forbid", populate_by_name=True, protected_namespaces=())` (common.py 201–205). Unknown
fields rejected everywhere; `schema`/`not` aliases round-trip via `populate_by_name`.

### 5.2 `capability.py`

`CapabilityDescriptor` (115–130): `descriptor_version: Literal["1.0"]`, `capability_id`, `version`,
`title`, `description?`, `kind: CapabilityKind`, `side_effect: SideEffect`, `idempotent?`,
`inputs`/`outputs: List[SchemaIO]`, `config_schema?`, `runtime: Runtime = Field(...,
discriminator="kind")`, `constraints?`, `owner?`, `status: CapabilityStatus`. `@model_validator`
**`_runtime_kind_matches`** — `runtime.kind == kind.value`.
Enums: `CapabilityKind` = `skill, mcp, llm, deep_agent`; `SideEffect` = `read_only, side_effectful`;
`McpTransport` = `streamable_http, stdio, sse`.
**Runtime union** (101): discriminator `kind`. **`mcp` variant `McpRuntime` (60–69):**
`kind: Literal["mcp"]`, `endpoint: str`, `tools: List[str]` (min_length=1),
`transport: McpTransport = STREAMABLE_HTTP`, `headers: Dict[str,str] = {}`.
`Constraints` (104–107): `timeout_seconds: int = 120`, `max_retries: int = 2`,
`min_hitl_mode: Optional[HitlMode]`.

### 5.3 `artifact_schema.py`

`ArtifactSchemaRegistration` (26–33): `artifact_key`, `version`, `title`, `description?`,
`json_schema: Dict[str,Any]`, `compatibility: Compatibility = BACKWARD`, `tags?`, `status: ArtifactStatus`.
The embedded `json_schema` is free-form here; draft-2020-12 well-formedness is meta-validated by the seed
loader, not Pydantic.

### 5.4 `common.py`

- `ROLE_ID_RE = r"^role\.[a-z0-9_.]+$"` (34); `RoleId = Annotated[str, StringConstraints(pattern=ROLE_ID_RE)]`
  (43). Companion patterns (30–45): `SEMVER_RE`, `PACK_KEY_RE`, `CAP_ID_RE`, `ART_ID_RE`, `SHA256_RE`, etc.
- `HitlMode` (54–59): `none, review_after, approve_result, approve_actions, manual`.
- `_HITL_RANK` (64–70): `none:0, review_after:1, approve_result:1, approve_actions:2, manual:2`.
  `hitl_rank(mode)` (73–74); `hitl_mode_at_least(mode, floor)` (77–84) → `rank(mode) >= rank(floor)`.
- `VersionedRef` (91–180): `<id>@<spec>` value object. `is_pinned` (107–110) → `_PINNED_RE.match(spec)`;
  `matches(exact)` (112–114) → `satisfies(exact, spec)`; `parse(raw)` (130–143). Subclasses
  `CapabilityRef` (`prefix="cap"`), `ArtifactRef` (`prefix="art"`).
- **Semver matcher** in `semver.py`: `satisfies(version, spec)` (88–91) — exact pin, caret `^x.y.z`,
  space-separated bounded comparators (`>=,<=,>,<,=`).
- **`common.py` defines NO `Predicate`** — the `Predicate` union lives in `process_pack.py` (§5.1).

### 5.5 Versioning / backward-safety

- `manifest_version: Literal["1.0"]` (175) — only exact `"1.0"` validates. Same for
  `descriptor_version: Literal["1.0"]`.
- **`ContractModel` base `extra="forbid"`: yes** (common.py 195–209), inherited by every contract model.
- **Adding an OPTIONAL field (e.g. a conformance/coverage annotation) is backward-safe.** `extra="forbid"`
  rejects *unexpected* keys, not *absent optional* keys; an `Optional[...] = None` (or `default_factory`)
  field validates against existing docs. Direct precedent in-tree: `deep_agent_justifications` added for
  ADR-021 with default + inline "Additive; empty for every existing pack" (175/187–190); `McpRuntime.headers`
  default `{}`. Additive-optional does **not** need a `manifest_version` bump; only new *required* fields or
  type changes would.

**Seam:** inference must ultimately emit `ArtifactSchemaRegistration`, `CapabilityDescriptor`
(`runtime=McpRuntime`, `kind="mcp"`, `runtime.kind==kind`), and `ProcessPackManifest` (≥1 `TriageRule`, ≥1
`Binding`, each with an `Executor` discriminated on `type` and a full `Hitl`). All refs are `<id>@<spec>`
validated via `CapabilityRef`/`ArtifactRef`. The staged→strict boundary is the assemble step.
**Risk:** (1) `Hitl` required on every `Binding`, `role` required unless mode=none — bindings missing HITL
role fail assembly. (2) `triage_rules`/`bindings` min_length=1 and SoD `elements` min_length=2 — an
inference leaving these empty cannot assemble even as a "draft". (3) `extra="forbid"` — any speculative
provenance/coverage metadata must be a declared field. (4) `RequiresCapability.resolved` must be a pinned
exact version if set; inference should leave it `None` while draft.

---

## 6. agent-runtime engine — the execution model (Phase-2 spike inputs)

Paths under `backend/services/agent-runtime/`. Pins `langgraph>=0.2.0`,
`langgraph-checkpoint-mongodb>=0.1.0` (pyproject.toml:22-23); venv resolves **langgraph 0.4.6**.

### 6.1 File inventory

`app/engine/`: `compiler.py` (BPMN→`StateGraph`, the only build-time mapping, 40-99); `engine.py`
(`ProcessEngine` async orchestrator: bundle/graph caching, segment run/resume, HITL-task materialization,
terminal publishing, crash recovery, 62-327); `bundle.py` (`PackBundle` + `build_node_contexts`, 28-159);
`state.py` (`ProcessState` TypedDict + reducers, 14-58); `expr.py` (gateway condition mini-language,
19-48); `hitl.py` (framework-free HITL helpers: `ALLOWED_DECISIONS` + `compute_sod_excluded`, 15-54);
`task_runner.py` (`make_task_node` factory — per-node gather→execute→validate→HITL-gate→commit; where
`interrupt()` is raised, 72-401).
`app/engine/executor/`: `base.py` (`ExecutionContext`, `Executor` Protocol, `_run_blocking`, 19-73);
`core.py` (kind-dispatch skill/llm/mcp/deep_agent, 67-113); `dispatch.py` (`InProcessExecutor` +
`run_real_llm`, 30-129); `factory.py` (`build_executor`, native vs nemoclaw, fail-closed probe, 53-94);
`memo.py` (`MemoStore`/`InMemoryMemoStore`/`MongoMemoStore`/`memoized_execute`, 32-147); `sandboxed.py`
(`SandboxedExecutor`, nemoclaw); `deep_agent.py`; `mcp_client.py` (real MCP `tools/call`); `policy.py`;
`worker_runner.py`; `openshell/{broker,client}.py`.

### 6.2 compiler.py — BPMN → LangGraph

`compile_graph(bundle, executor, *, simulation, checkpointer)` (40) → one `StateGraph(ProcessState)` (60) →
`g.compile(checkpointer=checkpointer)` (99). Mapping: **task** → `add_node(element_id,
make_task_node(...))` (62-63), every task bound or `CompilerError` (56-58); **startEvent** →
`add_edge(START, resolve_node(start_out[0].target))` (83), exactly one start (47-48) + one outgoing
(81-82); **endEvent** → marker node `{"outcome": end_id}` then `add_edge(end_id, END)` (65-67, 102-106);
**sequenceFlow** → `add_edge` (97); **exclusiveGateway** → `add_conditional_edges(id, router, path_map)`
(93-95, `_build_gateway_router` 116-155).

**parallelGateway rejection** (42-46): `raise CompilerError(f"parallelGateway not supported in this slice:
{model.parallel_gateways} ...")`. **Chained-gateway rejection** — `resolve_node` (72-77): `if target in
gateways: raise CompilerError("chained gateways not supported ...")`. **Single-outgoing-per-task** (86-91):
`CompilerError(f"task '{element_id}' must have exactly one outgoing flow, has {len(outs)}")`.
**FAILURE_SINK** = `"__failure__"`, **FAILED_OUTCOME** = `"__failed__"` (32-33); `_failure_node` wired to
`END` (69-70), sets `outcome`/`last_error` (109-113); every gateway `path_map` includes `FAILURE_SINK`
(154). `ProcessEngine._complete` maps `FAILED_OUTCOME → _fail(...)` (engine.py:280-282).

### 6.3 HITL model — the crux

**Primitive: `interrupt()` + `Command(resume=...)`** (NOT `NodeInterrupt`). `from langgraph.types import
interrupt` (task_runner.py:24); `resume = interrupt(payload)` at `_run_reviewed` (280),
`_run_approve_actions` (335), `_run_manual` (376). Engine resumes with `graph.invoke(Command(resume=...),
cfg)` (engine.py:26,192).

**Interrupt → HitlTask materialization** (engine.py:206-274): `_run_segment` runs `graph.invoke` in a
thread (`asyncio.to_thread`, 209) and detects the interrupt in the result dict (216-219):
```python
if isinstance(result, dict) and "__interrupt__" in result:
    payload = result["__interrupt__"][0].value
    state = await asyncio.to_thread(lambda: graph.get_state(cfg).values)
    await self._materialize_task(instance, payload, state)
```
Payload from `_gate_payload` (task_runner.py:253-265): `element_id`, `hitl_mode`, `role`, `kind`, `title`,
`artifacts`, optional `proposed_actions`. `_materialize_task` persists a `HitlTask` via `self._hitl.insert`
(262-263), sets `WAITING_HITL` (264-267), publishes `HitlTaskCreatedEvent` (270-274). SoD exclusions from
`state["actor_log"]` (231-233). The LangGraph checkpoint holds the suspended node state; the HitlTask doc is
a separate projection of the review payload.

**Resume replays the node from the top** (task_runner.py:6-14 docstring: *"Because LangGraph re-executes the
interrupted node from the top on each resume, capabilities must be deterministic..."*). `interrupt()`
returns the resume value on replay; everything **above** it re-runs. Idempotency: (1) **memoization**
(memo.py) keyed on `(process_instance_id, element_id, inputs_hash, attempt)` (47-48), `memoized_execute`
(108-147) — but **off by default in native mode** (enabled only when `MEMOIZE_CAPABILITIES` set AND a memo
store wired: dispatch.py:37, factory.py:64-65,81; nemoclaw defaults it on, factory.py:85). With native
default, replay genuinely re-executes (safe only because simulation is deterministic). (2) `memo_attempt`
counter via the reject/re-run loop (task_runner.py:279-302).

**SoD / role check** in `HitlDecisionService.claim` (services/hitl_service.py:44-63):
`self._check_sod(task, actor_id)` then `if task.role not in actor_roles: raise HitlError(403, ...)`. Roles
come from the token (`routers/hitl_tasks.py:64`), re-checked at decide (77, 122-124). Exclusion set from
`compute_sod_excluded` (hitl.py:29-54).

### 6.4 state.py

`ProcessState(TypedDict, total=False)` (21-28): `envelope`, `artifacts`
(`Annotated[Dict, merge_dicts]` — later deltas overlay, 14-18,23), `actor_log`
(`Annotated[List, operator.add]` — append, 24), `trace`, `pack`, `outcome`, `last_error`. Only `artifacts`
and `actor_log` have reducers; the rest last-write. JSON-serializable so the Mongo checkpointer persists per
node boundary (state.py:5-6 — "that checkpoint trail is the audit record"). No per-branch/versioned channel,
no `Send`-oriented list channels.

### 6.5 bundle.py

`PackBundle` bundles `manifest`, `resolution`, `bpmn_model`, `descriptors`, `schemas`, `bpmn_xml` (28-35).
Construction: `_fetch_bundle` from registry (engine.py:111-140) and `from_seed_dir` (bundle.py:52-86).
Caching is in the **engine**: `ProcessEngine._bundles`/`_graphs` keyed by `(pack_key, version)` under a lock,
cached **forever** ("packs are immutable once active", engine.py:80-83,100-155). `build_node_contexts`
(120-159) assembles one `NodeContext` per bound element.

### 6.6 expr.py

One regex `_COND` (19) supports exactly `<dotpath> (== | = | !=) "literal"`. Only equality (`==`/`=`) and
inequality (`!=`) (31-32, 44-48). No AND/OR, no numeric/relational, no unquoted literals, no functions.
Dot-path resolves against `state.artifacts` (35-41). Outside subset → `ConditionSyntaxError`, surfaced with
the gateway id (compiler.py:136-138).

### 6.7 Checkpointing

Saver: **`MongoDBSaver`** (sync) from `langgraph.checkpoint.mongodb`, guarded import (engine.py:29-32).
`_make_checkpointer` over a **sync** `pymongo.MongoClient` (85-95). **`AsyncMongoDBSaver` not used** — hence
every graph call runs in `asyncio.to_thread` (209, 218, 317). `thread_id` = process instance id: `cfg =
{"configurable": {"thread_id": instance.process_instance_id}}` (207). Checkpoints per superstep/node
boundary. **Crash recovery** `ProcessEngine.recover()` (194-204) sweeps `RUNNING` instances and calls
`_run_segment(inst, graph, None)` — `None` resumes from the last checkpoint on the same `thread_id`.
`WAITING_HITL` instances are not swept (they resume via a human decision).

### 6.8 Parallel / fan-out — entirely unused

Grep for `Send`, `superstep`, `NodeInterrupt`, `interrupt_before/after` returns **nothing** except the
single `add_conditional_edges` at compiler.py:95. **No `Send`** anywhere (though `from langgraph.types
import Send` imports fine at 0.4.6 — available, never used). **No multiple outgoing edges from any node**
(single-outgoing invariant, compiler.py:88-91; parallelGateway rejected). **No superstep parallelism** —
every router returns one target string (141-151). The graph is a strictly linear/branching DAG with at most
one active node per superstep.

### 6.9 Simulation vs real, native vs nemoclaw, kind-dispatch

- `AGENTRT_SIMULATION_MODE` → `SIMULATION_MODE: bool = True` (config.py:39). *Whether* a capability is real;
  threaded via `compile_graph(..., simulation=...)` → `ExecutionContext.simulation` → branched in
  `core.execute_capability` (core.py:88,94).
- `AGENTRT_EXECUTION_MODE` → `EXECUTION_MODE: Literal["native","nemoclaw"] = "native"` (config.py:47).
  *Where* a capability runs. `build_executor` (factory.py:63-85): native → `InProcessExecutor`; nemoclaw →
  `SandboxedExecutor` over OpenShell, fail-closed probe (`NemoClawUnavailable`, 71-76). Axes are orthogonal
  (config.py:41-44).
- **Kind-dispatch** in `core.execute_capability` (67-113) — single `if kind == ...` ladder shared by native
  and sandbox worker. `deep_agent` fail-closed unless a runner is supplied (nemoclaw-only, 77-85).

**Seam:** clean seams are (1) the `Executor` Protocol (base.py:58-73) — swappable capability substrate; (2)
`compile_graph` (40) — a single Mongo-free deterministic BPMN→graph point; (3) the interrupt payload
contract (`_gate_payload`, 253-265) + `Command(resume=...)` — a narrow serializable HITL boundary; (4)
`thread_id = process_instance_id` — one instance ⇄ one thread ⇄ one checkpoint lineage.
**Risk:**
- **(a) Extending natively to parallel/event/boundary is a rewrite, not an extension.** The compiler rests on
  hard single-token invariants (one start, one outgoing/task, parallel rejected, chained rejected); the
  router returns one string; `ProcessState` has no branch/correlation channels. Fan-out needs `Send`,
  concurrent-write reducers, and — critically — reworking HITL: the engine assumes **one** interrupt per
  segment (`result["__interrupt__"][0]`, 217) and **one** `WAITING_HITL` per instance (264-267), so two
  concurrent human gates on parallel branches are unrepresentable. Boundary/timer/message events have no
  node mapping at all.
- **(a′) Replay-from-top is a standing correctness hazard.** Non-deterministic capabilities are safe only
  because memoization is on — yet memoization is **off by default in native mode** (factory.py:64,
  dispatch.py:37). Any real native run with an ungated capability above `interrupt()` re-invokes the model on
  resume and could commit an artifact the human never reviewed. Documented (memo.py:1-19), default posture
  latent.
- **(b) Mapping onto an external engine's ready-task-list model (e.g. SpiffWorkflow) is architecturally
  closer than extending LangGraph for parallelism.** The engine already treats execution as *"run a segment
  until the next HITL interrupt or END"* (engine.py:6-8) and resumes via an external decision payload keyed by
  instance id — essentially Spiff's ready-task list + persist + resume. Carry-over seams:
  `NodeContext`/`build_node_contexts` and the `Executor` Protocol are engine-agnostic. What fights: LangGraph
  checkpoints are opaque channel snapshots keyed by `thread_id` and *are* the audit record (state.py:5) +
  crash recovery (194-204); Spiff serializes an explicit token/task tree — a swap means re-homing durable
  state + memo keying onto Spiff task instance ids. But Spiff natively models the parallel/boundary/event
  frontier this compiler refuses.

---

## 7. webui — onboarding wizard & BPMN rendering

### 7.1 Wizard component & steps

The wizard lives in one file: `webui/src/features/registry/OnboardingWizard.tsx` (~1046 lines). Entry
`OnboardingWizard` (:58-62) branches on `sessionId` → `StartScreen` (create/resume) or `SessionWizard`
(stepper). All steps co-located:

| # | Label (`STEPS`, :35-37) | Component | Transition |
|---|---|---|---|
| 1 | Basics | `BasicsStep` (:219) | — (created via `createOnboardingSession`) |
| 2 | BPMN | `BpmnStep` (:240) | `attachOnboardingBpmn` |
| 3 | Capabilities | `CapabilitiesStep` (:374) | `introspectMcp` + `setOnboardingCapabilities` |
| 4 | Bindings | `BindingsStep` (:509) | `setOnboardingBindings` |
| 5 | Triage | `TriageStep` (:640) | `setOnboardingTriage` |
| 6 | Policies | `PoliciesStep` (:715) | `setOnboardingPolicies` |
| 7 | Review & activate | `ReviewStep` (:858) | `assembleOnboarding` + `commitOnboarding` |

Assemble + Commit are collapsed into step 7 (`Validate`/`Activate` buttons, :917-926). Attach IS the BPMN
step.

**Thin server-driven state machine.** `SessionWizard` (:147-216) holds one `session`; steps are pure
renderers. `apply()` (:164-169) swaps in the returned session, toasts `last_cleared`, advances the step.
`STATE_STEP` (:38-41) maps the server `OnboardingState` back to a step index so a resumed session opens
correctly (:155).

**Error/422 surfacing.** `extractErrors(err)` (:45-56) normalizes `ApiError.detail` into
`{general, fields, findings}` — reads `detail.errors[]` (mapping `field ?? tool ?? ref ?? rule_id`, plus
`element_id`, `allowed_min_mode`) and `detail.findings[]`. All transition calls are `silent: true`
(registry.ts:231-261) so these render inline. Three styles: inline field errors (`StartScreen` :82-84;
`BindingsStep.submit` :554-570 keys `fieldErrs` by `element_id ?? field`, highlights the Card, count
banner); **findings banner** (`BpmnStep` :322-334 renders `findings[]` as a red "BPMN rejected" list
`f.code · f.element_id — f.message`); toast fallback. `ReviewStep`'s `ReportView` (:951-991) renders
`session.dry_run_report.findings` grouped by stage with per-error "Fix" buttons jumping back via a
`stageToStep` map.

### 7.2 BPMN rendering

**`bpmn-js` is integrated** (`"bpmn-js": "^17.11.1"`). Viewer `webui/src/features/registry/BpmnViewer.tsx`
(85 lines), exports `BpmnViewer` + a `BpmnMarker` interface. Lazily imports the **NavigatedViewer**
production build (:47): `const { default: NavigatedViewer } = await
import("bpmn-js/dist/bpmn-navigated-viewer.production.min.js");`. After `importXML(xml)` → `canvas.zoom("fit-viewport")` (:51-52).

**Renders in the wizard today, but modal-only.** `BpmnStep` mounts it in a `Dialog` behind a "View diagram"
button (disabled until XML present), `OnboardingWizard.tsx:271-279`, `<BpmnViewer xml={xml}
className="h-[70vh]" />`. The primary in-step BPMN feedback is the textual `InventoryCard` (:345-366)
listing service/user tasks + gateways as badges. Three total mount sites:
1. `OnboardingWizard.tsx:277` — wizard BPMN step, modal, **no markers**.
2. `PackDetailPage.tsx:123` — committed pack detail, **no markers**.
3. `ProcessDiagramView.tsx:60` — **the only marker-driven mount**: `<BpmnViewer xml={bpmn}
   markers={markers} …/>`, markers built from live steps (`ProcessDiagramView.tsx:19`).

**Element coloring already exists** via `canvas.addMarker(m.elementId, \`bpmn-state-${m.state}\`)`
(BpmnViewer.tsx:53-60), guarded in try/catch, re-run on a `markerKey` string (:37-38, :75). CSS classes
`.bpmn-state-done/current/failed` in `index.css:136-149`. **Confirmed absence: no coverage overlay** —
nothing colors elements by "executable (bound) vs documented (unbound)". `BpmnMarker.state` union
(`done|current|pending|failed`, :8) has no coverage/bound/unbound state; the wizard mount passes no markers.

### 7.3 BPMN step — XML input & attach payload

XML two ways into one shared `xml` state (:241): (a) file upload — hidden `<input type="file"
accept=".bpmn,.xml,…">` (:285-288) + drag-drop (:289-314); `loadFile` reads `file.text()` and records
`fileName` (:249-253); (b) paste `<Textarea id="bpmn">` (:316-320) — typing clears `fileName` (:318). So
`bpmn_file` is set only on upload. Attach (:255-263): `attachOnboardingBpmn(session_id, { bpmn_xml: xml,
bpmn_file: fileName || undefined })` → `PUT /onboarding/{id}/bpmn` (registry.ts:238-240). (The committed-pack
path `uploadBpmn` differs — `PUT /packs/…/bpmn` with `rawBody {content, contentType:"application/xml"}`.)

### 7.4 API client & onboarding types

**Generated client exists but does NOT cover onboarding.** `npm run gen:api` → `scripts/gen-api.mjs` runs
`openapi-typescript` per service → `webui/src/api/gen/{stub,ingestor,runtime,registry,identity}.ts`
("GENERATED — DO NOT HAND-EDIT"); `gen:api:check` gates drift. **Confirmed absence:** `grep -c "onboarding"
src/api/gen/registry.ts` → `0`; no `Onb*` in `gen/`. Onboarding endpoints emit no FastAPI `response_model`
into OpenAPI, so (like two runtime instance endpoints, gen-api.mjs:10-13) they're hand-written.
**All onboarding TS types are hand-maintained** in `webui/src/api/services/registry.ts` (comment :158-161:
"Shapes mirror `app/models/onboarding.py` — kept in sync by hand"). Types: `OnboardingState`, `OnbBasics`,
`OnbBpmnInventory`, `OnbStagedArtifact`, `OnbStagedCapability`, `OnbBindingIO`, `OnbStagedBinding`,
`OnbTriageRule`, `OnbGatewayVariable`, `OnbSod`, `OnbRoleMeta`, `OnbCommitStep`, `OnboardingSession`
(:190-198), plus `IntrospectedTool`/`IntrospectMcpResponse`/`CapabilityToolSelection`/`BindingInput`.
`ValidationReport`/`ValidationFinding` likewise hand-captured (:14-30).

**Seam:** a full-diagram render + coverage overlay plugs in at two existing joints: (1) **Render** — `BpmnStep`
(:340, where `InventoryCard` renders on `session.bpmn`) is the natural inline mount; `BpmnViewer` already
accepts `xml` + `markers` and is battle-tested inline in `ProcessDiagramView.tsx:60`. (2) **Coverage overlay**
— extend `BpmnMarker.state` (:8) with e.g. `bound`/`unbound` + matching `.bpmn-state-*` classes
(index.css:136-149); the paint loop (:53-60) needs no change. Marker source data is already client-side:
`session.bpmn.service_tasks/user_tasks` (documented set) vs `session.bindings[].element_id` (executable set),
mapping onto the row state at :582-619.
**Risk:** (1) **Hand-sync drift** — the whole onboarding contract is hand-copied from `onboarding.py`, outside
`gen:api:check`; a backend rename ships a silently-wrong UI with no CI signal. (2) **Coverage semantics live
server-side** — a client-derived bound/unbound set-diff can disagree with the authoritative
`dry_run_report`; deriving overlay state from `dry_run_report.findings[].element_id` avoids divergence but
means no coloring until Validate. (3) **Modal-only + lazy import** — moving to an always-inline canvas loads
the heavy NavigatedViewer eagerly and re-imports per `xml`/`markerKey` change → a re-import per keystroke on
the textarea unless debounced.

---

## 8. openspec/ & ADR/docs conventions

**`openspec/` is an OpenSpec (spec-driven-change) scaffold, not the authored docs.** `openspec/config.yaml:1`
declares `schema: spec-driven`; the rest is commented template guidance (`:3-21`). Structure:
`config.yaml`, `specs/` (empty), `changes/` containing only `changes/archive/` (empty). **Confirmed
absences:** no `openspec/README.md`, no `.md` files, no active/archived changes, no populated specs. No
references to "openspec" in `README.md` or `backend/docs/*.md`. Effectively initialized-but-unused.

**Authoring happens in `backend/docs/adr/`.** Naming: `ADR-NNN-kebab-slug.md`, zero-padded 3-digit, currently
`ADR-007 … ADR-026` (20 files; 001–006 absent). Example: `ADR-026-dynamic-assignable-roles-per-pack-role-registry.md`.
Header pattern (`ADR-026-...md:1-11`):
```
# ADR-026 — <Title>

- **Status:** Accepted
- **Date:** 2026-07-15
- **Related:** **ADR-014** ... **ADR-025** ... `FAQ/Roles_FAQ.md`, `amendia_services_reference.md` §4/§5 ...
- **Supersedes:** ...

## Context
```
So a new ADR: H1 `# ADR-NNN — Title`, then a bullet block (`**Status:**`, `**Date:** YYYY-MM-DD`,
`**Related:**`, optional `**Supersedes:**`), then `## Context` and further `##` sections.

**Maintained reference docs** live in `backend/docs/` as `amendia_*.md` (snake_case) plus special cases:
services reference `amendia_services_reference.md`; contracts `amendia_contracts_reference.md`
(+ `amendia_platform_contracts_v1.md`); persona map `amendia_persona_map.md`; user guide
`Amendia_User_Guide.md`; admin guide `amendia_admin_user_management_guide.md`; FAQ `FAQ/Roles_FAQ.md`;
others `amendia_agent_runtime_execution_pipeline.md`, `amendia_auth_architecture.md`,
`amendia_llm_configuration_guide.md`, `amendia_nemoclaw_operator_runbook.md`,
`amendia_secure_runtime_nemoclaw_plan.md`, `amendia_build_plan.md`, `amendia_project_brief.md`,
`wire-transfer-exception-reference.md`.

**Seam:** cross-doc references are text citations inside ADR `**Related:**` blocks (manually maintained).
**Risk:** `openspec/` is wired but empty and unreferenced while real records live in `backend/docs/adr/`; a
contributor invoking OpenSpec tooling would author into a disconnected location — the two systems can
silently diverge. (This dossier itself lives at `backend/docs/amendia_bpmn_conformance_dossier.md`, per the
reference-doc convention, not in `openspec/`.)

---

## Final synthesis

### 1. To accept full BPMN without executing it — what must change

Two structures, on two sides of the lib/registry boundary:

- **In `libs/amendia_bpmn` (the reject→classify pivot):**
  1. **Retain unknowns.** `BpmnModel` (model.py:51-67) has no field for unrecognized elements; the parser's
     `else` branch (parser.py:85-90) records only a `Finding` and drops the element. Add a retention
     collection — e.g. `documented_elements: List[<id, kind, raw?>]` (and, for Phase 1, richer topology:
     retained flows/lanes/pools/events/data-objects) — and have the `else` branch (and the event/gateway
     sub-kinds currently collapsed) *classify* into it instead of discarding.
  2. **Add a severity/classification tier to `Finding`.** `Finding` (model.py:32-38) has no severity; the
     docstring hard-codes "always error." Add `severity` (or a per-element `tier`: `executable_now` /
     `documented_only` / `unknown`) so the parser can mark an accepted-but-not-executable element as a
     *warning/annotation* rather than an error.
- **In process-registry:** the `Severity` enum + `ok = not has_errors` already exist
  (`app/validation/report.py:14-17,64-69`) — **warnings already don't block activation**, so no new severity
  machinery is needed registry-side. The change is in the **adapter** `app/validation/bpmn.py:38-40`, which
  currently forces *every* lib finding to `Severity.ERROR` at stage 1 — it must map `documented_only`/`unknown`
  findings to `WARNING`/`INFO`. And **onboarding** `_parse_and_check_bpmn` (onboarding.py:609-644), which
  builds its own dict findings and 422s on *any* of them, must stop rejecting documented-only elements — its
  two extra codes (`bpmn_parallel_gateway_unsupported`, `bpmn_chained_gateway_unsupported`) become
  annotations, not hard errors. Named structures to touch: `BpmnModel`, `Finding` (lib);
  `parse_and_validate` mapping (bpmn.py:38-40); `_parse_and_check_bpmn` strictness (onboarding.py:622-632).
  `ValidationReport.Severity`/`ok` need no change.

### 2. What already supports a partially-inferred draft — and what blocks it

- **Supports:** `OnboardingSession` *is* the staging area, and every staged model is permissive
  `BaseModel` (onboarding.py docstring 6-10) — a rough/partial inferred draft lives fine on the session
  and is round-tripped whole to the UI on every transition. The `mcp_introspect` template
  (`infer_capability`/`suggest_ids`/`normalize_artifact_schema`, §4.2) is exactly the shape Phase-1 inference
  mirrors. On the contract side, **additive optional fields are backward-safe** under `extra="forbid"`
  (precedent `deep_agent_justifications`, §5.5) — so a conformance/coverage annotation on the manifest is
  safe.
- **Blocks:** (a) `BpmnInventory` (onboarding.py:71-80) is topology-thin — no edges, conditions, targets,
  lanes, pools, events, or data objects — so inference from BPMN structure has almost nothing to consume
  today; growing it is a prerequisite. (b) At **assemble**, the strict contracts bite:
  `ProcessPackManifest` requires `triage_rules` min_length=1 and `bindings` min_length=1, each `Binding`
  needs a full `Hitl` (role required unless mode=none), SoD `elements` min_length=2, and
  `RequiresCapability.resolved` must be pinned if set (§5.1). A partial draft can be **staged** but cannot
  **assemble** until those minimums are met. (c) `extra="forbid"` means any provenance/coverage metadata
  the inference wants to carry must be a *declared* field, not smuggled.

### 3. Phase 2 — extend-native vs embed-SpiffWorkflow (grounded)

**Extend-native.** The seams are genuinely clean: one `compile_graph` translation point, a swappable
`Executor` Protocol, a narrow serializable interrupt payload, and `thread_id = instance` giving crash
recovery and HITL resume the same mechanism. But growing toward the Common Executable sub-class is a
**rewrite of the compiler and the HITL/instance model, not an extension**. The compiler is built on hard
single-token invariants (one start, one outgoing per task, parallel/chained rejected; compiler.py:42-91) and
`ProcessState` has no branch/correlation channels (state.py:21-28). The binding constraint is HITL: the
engine assumes exactly one interrupt per segment (`result["__interrupt__"][0]`, engine.py:217) and one
`WAITING_HITL` per instance (264-267), so **two concurrent human gates on parallel branches are
unrepresentable** without redesigning the instance/HitlTask model, adopting `Send` (available at 0.4.6,
unused), and adding concurrent-write reducers. Boundary/timer/message events have *no* node mapping at all.
And replay-from-top (task_runner.py:6-14) with native-default memoization *off* (factory.py:64) is a latent
correctness hazard that parallelism amplifies.

**Embed-SpiffWorkflow.** Architecturally *closer* to what already exists: the engine treats execution as
"run a segment until the next HITL interrupt or END, then resume via an external decision payload keyed by
instance id" (engine.py:6-8) — which is essentially Spiff's ready-task-list + persist + resume, and Spiff
*natively* models the parallel/boundary/event frontier this compiler refuses. Engine-agnostic seams carry
over (`build_node_contexts`, the `Executor` Protocol). What fights: LangGraph checkpoints are opaque channel
snapshots keyed by `thread_id` and *are* the audit record (state.py:5) and the crash-recovery substrate
(engine.py:194-204); Spiff serializes an explicit token/task tree, so a swap means **re-homing durable state
and the memo keying (memo.py:47) onto Spiff task-instance ids**, reconciling two execution/audit models, and
taking a new dependency. Net: extend-native keeps a clean-but-linear path and pays a compiler+HITL rewrite for
the multi-task frontier; embed-Spiff inherits the frontier and pays a durable-state/audit re-homing plus a
second execution model to integrate. The spike should target exactly the concurrent-HITL representability
gap and the checkpoint/audit re-homing cost — those, not gateway syntax, are the decision.

### 4. Top 5 unknowns/risks to decide before writing implementation prompts

1. **Target `BpmnInventory` shape for Phase 1.** Inference of lanes→roles, pools/message-flows→MCP
   candidates, events→SLA/escalation, DMN→decision capability, data-objects→artifact seeds all require
   topology the model does not capture today. Decide the enriched inventory schema (edges, conditions, lanes,
   pools, event/boundary defs, DMN linkage) *before* inference — it gates everything in Phase 1.
2. **The classification taxonomy.** What tiers exactly (`executable_now` / `documented_only` / `unknown`),
   is it a per-element tag on `BpmnModel` or a separate coverage report, and does it live in the lib
   `Finding.severity` or a new field? This one decision drives the lib change, the `bpmn.py` severity
   mapping, and the webui overlay simultaneously. (Also: is DMN in-BPMN or a sibling artifact?)
3. **Native-default memoization posture.** Memoization is off by default in native mode
   (factory.py:64) — a latent replay hazard that Phase 2 parallelism would amplify. Decide whether to flip it
   on-by-default (or gate real native execution) *before* touching execution semantics.
4. **Build-vs-buy commit criterion.** The real fork is concurrent-HITL representability (one `WAITING_HITL`
   per instance today). Does the roadmap actually require parallel *human* gates, or is sequentializing the
   fan-out acceptable? The spike must answer this plus the checkpoint/audit re-homing cost — not gateway
   coverage.
5. **Hand-maintained onboarding types.** The entire onboarding contract (session shape, `extractErrors`'s
   assumed `detail.errors[]`/`findings[]` keys) is hand-synced to `webui/src/api/services/registry.ts`
   outside `gen:api:check`. Any Phase-0/1 model change (inventory growth, new manifest annotation, new finding
   severity) ships a silently-wrong UI with no CI signal. Decide whether to bring onboarding under `gen:api`
   first, or accept the drift risk.

**Latent inconsistency to note for the planner:** onboarding selects the target `<process>` by
`isExecutable="true"` preference (`_extract_process_id`, onboarding.py:650-659) while the shared parser
matches on exact `expected_process_id` (parser.py:44-45) — worth unifying as part of Phase 0.
