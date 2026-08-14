# Claude Code prompt — ADR-064 P1: cohort SLA **definition model + DAG validation** (process-registry, backend-only)

First phase of **ADR-064 (Cohort SLAs)**. Add the design-time **expectation graph** (a DAG of segments with
AND/XOR splits, expected/conditional nodes) and its **SLA specs** to the cohort *definition*, plus
**well-formedness validation**. This phase is **storage + validation only** — no runtime scheduling
(P2/agent-runtime), no GLEA (P3), no editor UI (P4). Read ADR-064 first:
`backend/docs/adr/ADR-064-cohort-slas-and-cross-system-timing-expectations.md`, and the authoring guide
`backend/docs/methodology/cohort_authoring_guide.html` for the intended semantics.

## Why

Cohort SLAs need the author to declare *what segments are expected and in what order* — an observer can't infer
it. That declaration is a DAG on the cohort definition. Everything downstream (P2 timers, P3 surfacing, P4
editor) builds on this model + its validation, so it lands first and standalone. **When no graph is declared, a
definition behaves exactly as ADR-063 today** (pure observer, no SLAs) — the graph is purely additive.

## Read first (reuse the existing shapes + style)

- `backend/services/process-registry/app/models/cohort.py` — `CohortDefinitionBase` /
  `CohortDefinitionCreate` / `CohortDefinitionUpdate` / `CohortDefinition`. The graph fields go here.
- `backend/services/process-registry/app/routers/cohort.py` — `register_definition` (POST) and
  `update_definition` (PUT) already call the shared **`_validate_close`** and are `_OWNER`-gated. Add a sibling
  **`_validate_expectation_graph`** and call it in both, right after `_validate_close`.
- `backend/services/process-registry/app/dal/cohort_def_repo.py` — `insert` (`to_doc`), `get`/`list`
  (**check `_PROJECTION`** — it must include the new field or reads will silently drop the graph), and `update`
  (`$set` of the patch — the graph must be in the set so PUT replaces it).
- `backend/services/process-registry/app/validation/pack_validator.py` — mirror its style; in particular
  **`_forward_reach`** (a forward-reachability BFS over a node map) is the pattern to reuse for graph
  reachability + cycle detection. Don't add a graph library — a small topological check is enough.
- `backend/services/process-registry/tests/test_cohort_phase2.py` + `tests/conftest.py` — the existing cohort
  definition tests (owner-gate, close-schema validation, round-trip). Mirror them; add the new cases here or in a
  new `tests/test_cohort_sla_definition.py`.

## The model (add to `models/cohort.py`)

Add these shapes (finalise field names to match repo conventions, but keep the semantics exact). Use pydantic
`Literal` enums so bad values are rejected at parse time.

- Reserved node ids: `START = "__start__"`, `CLOSE = "__close__"` (module constants). Segment nodes are keyed by
  the member's **`pack_key`**.
- `NodeType = Literal["expected","conditional"]`, `SplitType = Literal["and","xor"]`,
  `Moment = Literal["arrival","completion"]`, `SlaClock = Literal["wall","business"]`,
  `SlaOwner = Literal["external","amendia","shared"]`.
- **`EdgeSla`** — a time promise on an edge: `anchor_moment: Moment = "completion"` (of the edge's `from` node;
  forced to cohort-open when `from == START`), `satisfy_moment: Moment = "arrival"` (of the `to` node; the
  close-received event when `to == CLOSE`), `deadline_seconds: int` (> 0), `at_risk_seconds: int = 0`
  (0 <= at_risk < deadline), `clock: SlaClock = "wall"`, `owner: SlaOwner`.
- **`NodeSla`** — a segment's own runtime (arrival->completion) promise: `deadline_seconds`, `at_risk_seconds`,
  `clock`, `owner` (conventionally `amendia`). Same numeric rules.
- **`CohortNode`** — `node_id: str` (a segment `pack_key`; unique; not a reserved id),
  `node_type: NodeType = "expected"`, `runtime_sla: Optional[NodeSla] = None`.
- **`CohortEdge`** — `from_node: str` (a `node_id` or `START`), `to_node: str` (a `node_id` or `CLOSE`),
  `split: SplitType` (the classification of `from_node`'s out-edge set — stored per edge, validated consistent),
  `sla: Optional[EdgeSla] = None`.
- **`EndToEndSla`** — the whole-case promise (cohort-open -> cohort-close): `deadline_seconds`,
  `at_risk_seconds`, `clock`, `owner: SlaOwner = "shared"`.
- **`ExpectationGraph`** — `nodes: List[CohortNode]`, `edges: List[CohortEdge]`,
  `end_to_end_sla: Optional[EndToEndSla] = None`.
- Add **`expectation_graph: Optional[ExpectationGraph] = None`** to **`CohortDefinitionBase`** (flows to Create +
  stored `CohortDefinition`) **and** to **`CohortDefinitionUpdate`** (so inline edit can set/replace it,
  forward-only). Default `None` = today's behaviour.

Concrete example (the ACH cohort is the simple linear case; XOR shown for completeness):

```json
"expectation_graph": {
  "nodes": [
    {"node_id": "ach-exposure-assess",  "node_type": "expected"},
    {"node_id": "ach-decision-enforce", "node_type": "expected",
     "runtime_sla": {"deadline_seconds": 1800, "at_risk_seconds": 1200, "clock": "wall", "owner": "amendia"}},
    {"node_id": "ach-closeout",         "node_type": "expected"}
  ],
  "edges": [
    {"from_node": "__start__",            "to_node": "ach-exposure-assess",  "split": "and",
     "sla": {"satisfy_moment": "arrival", "deadline_seconds": 7200,  "at_risk_seconds": 5400, "clock": "wall",     "owner": "external"}},
    {"from_node": "ach-exposure-assess",  "to_node": "ach-decision-enforce", "split": "and",
     "sla": {"anchor_moment": "completion", "satisfy_moment": "arrival", "deadline_seconds": 14400, "at_risk_seconds": 10800, "clock": "business", "owner": "external"}},
    {"from_node": "ach-decision-enforce", "to_node": "ach-closeout",         "split": "and"},
    {"from_node": "ach-closeout",         "to_node": "__close__",            "split": "and"}
  ],
  "end_to_end_sla": {"deadline_seconds": 86400, "at_risk_seconds": 64800, "clock": "business", "owner": "shared"}
}
```

## Validation (`_validate_expectation_graph`, raise `HTTPException(422, ...)` with clear messages)

Call it in `register_definition` and `update_definition` **only when `expectation_graph` is present** (absent ->
skip; today's behaviour). Rules:

1. **Node ids** unique; none equals a reserved id (`__start__`/`__close__`).
2. **Edge endpoints resolve:** every `from_node`/`to_node` is either an existing `node_id` or the correct
   reserved id (`START` may be a `from`, `CLOSE` may be a `to`). Unknown ref -> reject.
3. **Boundaries:** `START` has no incoming edges and >=1 outgoing; `CLOSE` has no outgoing and >=1 incoming.
4. **Acyclic** (topological check; reject on any cycle).
5. **Reachability** (mirror `_forward_reach`): every segment node is reachable from `START` **and** can reach
   `CLOSE` — no orphans, no dead-ends.
6. **Split consistency:** all out-edges of a given `from_node` share the same `split` value.
7. **Split <-> node-type coupling (the core invariant):** a node reached by any **XOR** edge must be
   `conditional`; a node reached only by **AND**/plain edges must be `expected`. (So XOR branches are exactly the
   conditional segments; you can't have an "expected" XOR branch or a "conditional" AND branch.)
8. **SLA numerics** (each `EdgeSla`/`NodeSla`/`EndToEndSla`): `deadline_seconds > 0` and
   `0 <= at_risk_seconds < deadline_seconds`. (Enums are enforced by `Literal` at parse; this cross-field check is
   the one to add explicitly.)

**Do not** validate `node_id` against real pack membership — packs may be assigned before or after the definition
exists (forward-only). Referencing a not-yet-assigned `pack_key` is allowed. **Do not** enforce owner-by-moment
(e.g. completion=>amendia) — it's a convention, not a rule; leave `owner` author-chosen.

## Persistence

- `to_doc` already `model_dump(mode="json")`s — nested pydantic dumps fine. **Verify `_PROJECTION` in the repo
  includes `expectation_graph`** (or is exclusion-based) so `get`/`list` return it. **Verify `repo.update`'s
  `$set` includes `expectation_graph`** so PUT replaces it (forward-only; sending `null`/omitting clears or keeps
  per the inline-edit full-representation semantics already in place).

## Do not

- Do not touch **agent-runtime** (no timers/scheduling — that's P2), **glea-service** (P3), or the **webui**
  feature code / editor (P4). Do not add new endpoints — reuse the existing owner-gated POST/PUT.
- Do not change ADR-063 behaviour: a definition with **no** `expectation_graph` must register, load, and drive
  `/resolve`/close exactly as today.
- Do not validate against pack membership, and do not add a graph/topology dependency (hand-rolled check).
- No git writes — leave the tree dirty; the operator owns commits.

## Acceptance

- A definition **without** `expectation_graph` registers, round-trips (GET), and behaves exactly as before
  (backward-compatible).
- The linear ACH example above (all `expected`, with edge + node + end-to-end SLAs) **registers and round-trips**
  (GET returns the full graph — proving `_PROJECTION` includes it); a valid **XOR** graph
  (`START->A->xor{B,C conditional}->CLOSE`) and a valid **AND** fan-out both pass.
- **Rejections (422) with clear messages:** a cycle; an orphan (unreachable from START); a dead-end (can't reach
  CLOSE); START-with-incoming or CLOSE-with-outgoing; an XOR branch marked `expected`; an AND/plain branch marked
  `conditional`; inconsistent `split` across one node's out-edges; an edge to an unknown node id; a reserved-id
  collision; `at_risk_seconds >= deadline_seconds`; `deadline_seconds <= 0`.
- **PUT** replaces the graph on an existing definition (forward-only), `created_at` preserved / `updated_at`
  bumped; **non-owner -> 403** still holds on POST + PUT.
- `pytest` (process-registry) green incl. the new cases. The **OpenAPI snapshot is re-dumped** (new schemas
  present) and **`webui/src/api/gen/registry.ts` regenerated** so `tsc`/`npm run build` stays green — the webui
  doesn't *use* the new fields yet (that's P4), but the generated types must compile.
- **Reviewer note:** the new validation is live only after `docker compose build process-registry` (+ restart).

## Final step — implementation report (required)

Write `backend/docs/_build-reports/claude_code_prompt_ADR064_phase1_cohort_sla_definition_model_report.md`
(uncommitted): (1) outcome one-liner; (2) the model additions (final field names, enums, reserved ids); (3) the
validation rules implemented + where hooked (POST/PUT), and any deviations from the list above; (4) persistence
notes (`_PROJECTION` / `update` `$set` confirmation); (5) verification — exact `pytest` / snapshot-dump /
`gen:api` / build commands + results, incl. the specific 422 cases; (6) backward-compat confirmation (no-graph
definitions unchanged); (7) follow-ups for P2 (which runtime anchors/events the timers will bind to). One screen.

## Working agreement

No git write commands — leave the tree dirty for Sandeep. Backend-only (process-registry); reuse `_validate_close`
placement, the `_OWNER` gate, and the `_forward_reach` style. The graph is **additive and optional** — zero
behaviour change when it's absent. Smallest change that lands a well-validated model for P2 to build on.
