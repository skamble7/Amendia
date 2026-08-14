# ADR-064 P1 — cohort SLA definition model + DAG validation: report

**This is P1 of 4** (definition model + validation, process-registry, backend-only). P2 (runtime scheduling,
agent-runtime), P3 (GLEA), P4 (webui editor) are separate prompts — none built here.

## 1. Outcome

The cohort **definition** can now carry an optional **expectation graph** (a DAG of segments with AND/XOR splits
and expected/conditional nodes) plus per-edge / per-node / end-to-end **SLA specs**, with owner-gated
well-formedness validation on create + update. **Purely additive: a definition with no `expectation_graph`
registers, round-trips, and drives `/resolve`/close exactly as ADR-063.** All suites green; webui types compile.

## 2. Model additions (`app/models/cohort.py`)

- Reserved ids: `START_NODE = "__start__"`, `CLOSE_NODE = "__close__"` (module constants). Segment nodes are keyed
  by the member's `pack_key`.
- `Literal` enums (parse-time rejection): `NodeType = expected|conditional`, `SplitType = and|xor`,
  `Moment = arrival|completion`, `SlaClock = wall|business`, `SlaOwner = external|amendia|shared`.
- `EdgeSla` (`anchor_moment=completion`, `satisfy_moment=arrival`, `deadline_seconds`, `at_risk_seconds=0`,
  `clock=wall`, `owner` **required**), `NodeSla` (same, `owner=amendia` default), `EndToEndSla` (same,
  `owner=shared` default).
- `CohortNode` (`node_id`, `node_type=expected`, `runtime_sla?`), `CohortEdge` (`from_node`, `to_node`, `split`,
  `sla?`), `ExpectationGraph` (`nodes`, `edges`, `end_to_end_sla?`).
- `expectation_graph: Optional[ExpectationGraph] = None` added to **`CohortDefinitionBase`** (→ Create + stored
  `CohortDefinition`) **and** **`CohortDefinitionUpdate`** (inline edit set/replace). Default `None` = today.

## 3. Validation (`_validate_expectation_graph`, `routers/cohort.py`)

A sibling of `_validate_close`, called in **both** `register_definition` (POST) and `update_definition` (PUT)
right after `_validate_close`, **only when `expectation_graph is not None`** (absent → skipped, ADR-063
behaviour). Raises `HTTPException(422, "expectation_graph invalid: …")` with a specific message. Rules:

1. node ids unique + none is a reserved id; 2. edge endpoints resolve (a `node_id` or the correct reserved id;
reserved-id misuse — `__close__` as source / `__start__` as target — checked before "unknown node"); 3.
boundaries (START: 0 incoming, ≥1 outgoing; CLOSE: 0 outgoing, ≥1 incoming); 4. **acyclic** (Kahn's topo sort —
no graph lib); 5. **reachability** (mirrors `_forward_reach`: forward DFS from START + reverse DFS from CLOSE —
every segment node reachable from START and can reach CLOSE); 6. split consistency (all out-edges of a node share
one `split`); 7. **split ↔ node-type** (reached by any XOR edge → `conditional`; reached only by AND/plain →
`expected`); 8. SLA numerics (`deadline_seconds > 0`, `0 ≤ at_risk_seconds < deadline_seconds`) on every
edge/node/end-to-end SLA.

**Deviations from the list:** none. As instructed, it does **not** validate `node_id` against pack membership
(forward-only) and does **not** enforce owner-by-moment (a convention — `owner` stays author-chosen). The
"START-has-incoming / CLOSE-has-outgoing" cases surface via the rule-2 reserved-id-misuse messages (`__start__
cannot be an edge target` / `__close__ cannot be an edge source`), which is stricter and clearer.

## 4. Persistence (no changes needed — confirmed)

- `_PROJECTION = {"_id": 0}` is **exclusion-based**, so `get`/`list` return `expectation_graph` — proven by the
  linear round-trip test (POST → GET returns the full nodes/edges/SLAs).
- `repo.update` does `updates = patch.model_dump(mode="json")` then `$set`, so `expectation_graph` is in the set
  → PUT **replaces** it; omitting it (default `None`) **clears** it (full-representation, forward-only) — proven
  by the PUT replace-then-clear test. `to_doc` (`model_dump(mode="json")`) dumps the nested graph fine.

## 5. Verification

- `process-registry`: `uv run --extra dev pytest` → **400 passed** (+17 in `tests/test_cohort_sla_definition.py`).
  Cases: no-graph backward-compat (GET `expectation_graph is null`); linear ACH graph registers + round-trips
  (nodes/edges/node-SLA/edge-SLA/end-to-end all returned); valid XOR + AND fan-out; PUT replace (created_at
  preserved / updated_at bumped) then clear; **non-owner → 403** on POST + PUT with a graph; and **12 parametrized
  422 rejections** — cycle, orphan, dead-end, `__start__`-as-target, `__close__`-as-source, XOR-branch-expected,
  AND-branch-conditional, inconsistent split, edge-to-unknown-node, reserved-id collision, `at_risk ≥ deadline`,
  `deadline ≤ 0` — each asserting the specific message.
- OpenAPI snapshot re-dumped (`python scripts/dump_openapi.py`) → new schemas present (`ExpectationGraph`,
  `CohortNode`, `CohortEdge`, `EdgeSla`, `NodeSla`, `EndToEndSla`); `test_openapi_snapshot` green.
- webui: `node scripts/gen-api.mjs` regenerated `src/api/gen/registry.ts` (carries the new types); `npm run build`
  (`tsc --noEmit && vite build`) → **exit 0, built in 1.82s**. The webui doesn't *use* the fields yet (P4) but the
  generated types compile.

## 6. Backward-compat

Confirmed: a definition **without** `expectation_graph` registers, GET-round-trips (`expectation_graph: null`),
and the ADR-063 close-classification/`/resolve` path is untouched. The existing cohort suites pass unchanged
inside the 400.

## 7. Follow-ups for P2 (runtime anchors the timers will bind to)

- **Node arrival** = member join-on-spawn (ADR-063 `member_joined`, keyed by `pack_key`); **node completion** =
  member terminal (`on_member_terminal` → `process_completed`/`process_failed`).
- **START** = cohort `opened`; **CLOSE** = the close-received event (drives `closing/closed`).
- **Edge SLA:** after `anchor_moment` of `from` (cohort-open when `from == __start__`), expect `satisfy_moment`
  of `to` (close-received when `to == __close__`) within `deadline_seconds`; **node runtime SLA** = arrival →
  completion of that segment.
- **Voiding:** an XOR sibling's arrival voids its siblings; the close voids any still-pending expectation — wire
  into the existing fail-soft join/close handlers, materialising a new `cohort_sla` timer kind on the ADR-027
  substrate, with `at_risk → breach` transitions and exactly-once compare-and-set (mirroring `finalize_if_drained`).
- **Reviewer note:** the new validation is live only after `docker compose build process-registry` (+ restart).
