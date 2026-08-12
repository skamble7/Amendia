# app/routers/cohort.py
"""ADR-063 Phase 2 — cohort DEFINITION registration/query (registry-owned)."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from amendia_auth import require_roles

from app.dal.base import DuplicateError
from app.dal.cohort_def_repo import CohortDefinitionRepository
from app.deps import get_cohort_def_repo
from app.models.cohort import (
    CLOSE_NODE, START_NODE, CohortDefinition, CohortDefinitionCreate, CohortDefinitionUpdate,
    ExpectationGraph,
)

router = APIRouter(prefix="/cohort", tags=["cohort"])

# Definition authoring is process-owner only (mirrors pack authoring).
_OWNER = Depends(require_roles("role.process.owner"))


def _validate_close(close_schema: Dict[str, Any], close_correlation_path: str) -> None:
    """The close schema must be a well-formed JSON Schema (it gates close-message recognition at /resolve), and
    the correlation path is the sole handle that resolves an instance, so it is required. Shared by create + update."""
    try:
        Draft202012Validator.check_schema(close_schema)
    except SchemaError as exc:
        raise HTTPException(status_code=422, detail=f"close_schema is not a valid JSON Schema: {exc.message}")
    if not close_correlation_path:
        raise HTTPException(status_code=422, detail="close_correlation_path is required")


def _bad_graph(msg: str) -> None:
    raise HTTPException(status_code=422, detail=f"expectation_graph invalid: {msg}")


def _check_sla_numerics(sla: Optional[Any], where: str) -> None:
    if sla is None:
        return
    if sla.deadline_seconds <= 0:
        _bad_graph(f"{where}: deadline_seconds must be > 0 (got {sla.deadline_seconds})")
    if not (0 <= sla.at_risk_seconds < sla.deadline_seconds):
        _bad_graph(f"{where}: at_risk_seconds must satisfy 0 <= at_risk < deadline "
                   f"(got at_risk={sla.at_risk_seconds}, deadline={sla.deadline_seconds})")


def _validate_expectation_graph(graph: ExpectationGraph) -> None:
    """Well-formedness of the ADR-064 DAG. Called only when a graph is present (absent → ADR-063 behaviour).
    Structural (ids/endpoints/boundaries/acyclic/reachability/split), the split↔node-type coupling, and SLA
    numerics — NOT pack membership (forward-only) and NOT owner-by-moment (a convention, author-chosen)."""
    node_ids = [n.node_id for n in graph.nodes]

    # 1) node ids unique + none reserved
    if len(node_ids) != len(set(node_ids)):
        dupes = sorted({x for x in node_ids if node_ids.count(x) > 1})
        _bad_graph(f"duplicate node ids: {dupes}")
    for nid in node_ids:
        if nid in (START_NODE, CLOSE_NODE):
            _bad_graph(f"node id '{nid}' collides with a reserved id")
    node_set = set(node_ids)

    # 2) edge endpoints resolve (a node_id or the correct reserved id) — check reserved-id misuse first
    for e in graph.edges:
        if e.from_node == CLOSE_NODE:
            _bad_graph("__close__ cannot be an edge source")
        if not (e.from_node == START_NODE or e.from_node in node_set):
            _bad_graph(f"edge from unknown node '{e.from_node}'")
        if e.to_node == START_NODE:
            _bad_graph("__start__ cannot be an edge target")
        if not (e.to_node == CLOSE_NODE or e.to_node in node_set):
            _bad_graph(f"edge to unknown node '{e.to_node}'")

    # adjacency (forward + reverse) + in-degree over ALL nodes (segments + reserved)
    all_nodes = node_set | {START_NODE, CLOSE_NODE}
    fwd: Dict[str, List[str]] = defaultdict(list)
    rev: Dict[str, List[str]] = defaultdict(list)
    indeg: Dict[str, int] = {n: 0 for n in all_nodes}
    for e in graph.edges:
        fwd[e.from_node].append(e.to_node)
        rev[e.to_node].append(e.from_node)
        indeg[e.to_node] = indeg.get(e.to_node, 0) + 1

    # 3) boundaries
    if indeg.get(START_NODE, 0) != 0:
        _bad_graph("__start__ must have no incoming edges")
    if len(fwd.get(START_NODE, [])) < 1:
        _bad_graph("__start__ must have at least one outgoing edge")
    if len(fwd.get(CLOSE_NODE, [])) != 0:
        _bad_graph("__close__ must have no outgoing edges")
    if indeg.get(CLOSE_NODE, 0) < 1:
        _bad_graph("__close__ must have at least one incoming edge")

    # 4) acyclic (Kahn's topological sort — a self-loop or back-edge leaves nodes unprocessed)
    deg = dict(indeg)
    queue = [n for n, d in deg.items() if d == 0]
    processed = 0
    while queue:
        u = queue.pop()
        processed += 1
        for v in fwd.get(u, []):
            deg[v] -= 1
            if deg[v] == 0:
                queue.append(v)
    if processed != len(all_nodes):
        _bad_graph("graph has a cycle")

    # 5) reachability (mirror _forward_reach): every segment node reachable from START and can reach CLOSE
    def _reach(start: str, adj: Dict[str, List[str]]) -> set:
        seen, stack = set(), [start]
        while stack:
            x = stack.pop()
            for y in adj.get(x, []):
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        return seen
    from_start = _reach(START_NODE, fwd)
    to_close = _reach(CLOSE_NODE, rev)
    for nid in node_ids:
        if nid not in from_start:
            _bad_graph(f"node '{nid}' is not reachable from __start__ (orphan)")
        if nid not in to_close:
            _bad_graph(f"node '{nid}' cannot reach __close__ (dead-end)")

    # 6) split consistency: all out-edges of a from_node share one split
    out_by_from: Dict[str, set] = defaultdict(set)
    for e in graph.edges:
        out_by_from[e.from_node].add(e.split)
    for frm, splits in out_by_from.items():
        if len(splits) > 1:
            _bad_graph(f"node '{frm}' has inconsistent split across its out-edges: {sorted(splits)}")

    # 7) split ↔ node-type: reached by any XOR edge → conditional; reached only by AND/plain → expected
    in_splits: Dict[str, set] = defaultdict(set)
    for e in graph.edges:
        in_splits[e.to_node].add(e.split)
    for n in graph.nodes:
        reached_by_xor = "xor" in in_splits.get(n.node_id, set())
        if reached_by_xor and n.node_type != "conditional":
            _bad_graph(f"node '{n.node_id}' is reached by an XOR edge but is '{n.node_type}' (must be 'conditional')")
        if not reached_by_xor and n.node_type != "expected":
            _bad_graph(f"node '{n.node_id}' is reached only by AND/plain edges but is '{n.node_type}' "
                       f"(must be 'expected')")

    # 8) SLA numerics (deadline > 0, 0 <= at_risk < deadline) on every edge/node/end-to-end SLA
    for e in graph.edges:
        _check_sla_numerics(e.sla, f"edge {e.from_node}->{e.to_node}")
    for n in graph.nodes:
        _check_sla_numerics(n.runtime_sla, f"node '{n.node_id}' runtime_sla")
    _check_sla_numerics(graph.end_to_end_sla, "end_to_end_sla")


@router.post("/definitions", response_model=CohortDefinition, status_code=201, dependencies=[_OWNER])
async def register_definition(
    body: CohortDefinitionCreate, repo: CohortDefinitionRepository = Depends(get_cohort_def_repo)
):
    _validate_close(body.close_schema, body.close_correlation_path)
    if body.expectation_graph is not None:
        _validate_expectation_graph(body.expectation_graph)
    try:
        return await repo.insert(CohortDefinition(**body.model_dump()))
    except DuplicateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/definitions", response_model=List[CohortDefinition])
async def list_definitions(repo: CohortDefinitionRepository = Depends(get_cohort_def_repo)):
    return await repo.list()


@router.get("/definitions/{cohort_def_id}", response_model=CohortDefinition)
async def get_definition(cohort_def_id: str, repo: CohortDefinitionRepository = Depends(get_cohort_def_repo)):
    d = await repo.get(cohort_def_id)
    if d is None:
        raise HTTPException(status_code=404, detail=f"unknown cohort definition '{cohort_def_id}'")
    return d


@router.put("/definitions/{cohort_def_id}", response_model=CohortDefinition, dependencies=[_OWNER])
async def update_definition(
    cohort_def_id: str, body: CohortDefinitionUpdate,
    repo: CohortDefinitionRepository = Depends(get_cohort_def_repo),
):
    """Inline-edit the MUTABLE fields of a definition (owner-only). ``cohort_def_id`` is immutable — the path
    identifies the target and the body carries no id. 404 if the definition doesn't exist."""
    _validate_close(body.close_schema, body.close_correlation_path)
    if body.expectation_graph is not None:
        _validate_expectation_graph(body.expectation_graph)
    updated = await repo.update(cohort_def_id, body)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"unknown cohort definition '{cohort_def_id}'")
    return updated


@router.delete("/definitions/{cohort_def_id}", status_code=204, dependencies=[_OWNER])
async def delete_definition(cohort_def_id: str, repo: CohortDefinitionRepository = Depends(get_cohort_def_repo)):
    await repo.delete(cohort_def_id)  # idempotent
