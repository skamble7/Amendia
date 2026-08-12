# tests/test_cohort_sla_definition.py
"""ADR-064 P1 — cohort SLA expectation-graph model + DAG validation (definition storage only, no runtime)."""
from __future__ import annotations

import pytest

BASE_DEF = {
    "cohort_def_id": "ach_exposure_cohort",
    "display_name": "ACH exposure",
    "close_schema": {"type": "object", "required": ["event", "case_id"],
                     "properties": {"event": {"const": "process_completed"}, "case_id": {"type": "string"}}},
    "close_correlation_path": "case_id",
    "close_outcome_path": "outcome",
}


def _linear_graph():
    return {
        "nodes": [
            {"node_id": "ach-exposure-assess", "node_type": "expected"},
            {"node_id": "ach-decision-enforce", "node_type": "expected",
             "runtime_sla": {"deadline_seconds": 1800, "at_risk_seconds": 1200, "clock": "wall", "owner": "amendia"}},
            {"node_id": "ach-closeout", "node_type": "expected"},
        ],
        "edges": [
            {"from_node": "__start__", "to_node": "ach-exposure-assess", "split": "and",
             "sla": {"satisfy_moment": "arrival", "deadline_seconds": 7200, "at_risk_seconds": 5400, "clock": "wall", "owner": "external"}},
            {"from_node": "ach-exposure-assess", "to_node": "ach-decision-enforce", "split": "and",
             "sla": {"anchor_moment": "completion", "satisfy_moment": "arrival", "deadline_seconds": 14400, "at_risk_seconds": 10800, "clock": "business", "owner": "external"}},
            {"from_node": "ach-decision-enforce", "to_node": "ach-closeout", "split": "and"},
            {"from_node": "ach-closeout", "to_node": "__close__", "split": "and"},
        ],
        "end_to_end_sla": {"deadline_seconds": 86400, "at_risk_seconds": 64800, "clock": "business", "owner": "shared"},
    }


def _xor_graph():
    return {
        "nodes": [
            {"node_id": "a", "node_type": "expected"},
            {"node_id": "b", "node_type": "conditional"},
            {"node_id": "c", "node_type": "conditional"},
        ],
        "edges": [
            {"from_node": "__start__", "to_node": "a", "split": "and"},
            {"from_node": "a", "to_node": "b", "split": "xor"},
            {"from_node": "a", "to_node": "c", "split": "xor"},
            {"from_node": "b", "to_node": "__close__", "split": "and"},
            {"from_node": "c", "to_node": "__close__", "split": "and"},
        ],
    }


def _and_fanout_graph():
    return {
        "nodes": [{"node_id": "a"}, {"node_id": "b"}, {"node_id": "c"}],
        "edges": [
            {"from_node": "__start__", "to_node": "a", "split": "and"},
            {"from_node": "a", "to_node": "b", "split": "and"},
            {"from_node": "a", "to_node": "c", "split": "and"},
            {"from_node": "b", "to_node": "__close__", "split": "and"},
            {"from_node": "c", "to_node": "__close__", "split": "and"},
        ],
    }


def _def(graph=None, cohort_def_id="ach_exposure_cohort"):
    body = {**BASE_DEF, "cohort_def_id": cohort_def_id}
    if graph is not None:
        body["expectation_graph"] = graph
    return body


def _update_body(graph="__omit__"):
    b = {k: v for k, v in BASE_DEF.items() if k != "cohort_def_id"}
    if graph != "__omit__":
        b["expectation_graph"] = graph
    return b


# --- backward-compat + valid graphs -----------------------------------------------------------------

async def test_no_graph_is_backward_compatible(client):
    r = await client.post("/cohort/definitions", json=_def())        # no expectation_graph
    assert r.status_code == 201, r.text
    got = (await client.get("/cohort/definitions/ach_exposure_cohort")).json()
    assert got["expectation_graph"] is None                          # ADR-063 behaviour, unchanged


async def test_linear_graph_registers_and_round_trips(client):
    r = await client.post("/cohort/definitions", json=_def(_linear_graph()))
    assert r.status_code == 201, r.text
    g = (await client.get("/cohort/definitions/ach_exposure_cohort")).json()["expectation_graph"]
    # proves _PROJECTION returns the full graph (nodes + edges + node/edge/end-to-end SLAs)
    assert [n["node_id"] for n in g["nodes"]] == ["ach-exposure-assess", "ach-decision-enforce", "ach-closeout"]
    assert len(g["edges"]) == 4
    assert g["nodes"][1]["runtime_sla"]["deadline_seconds"] == 1800
    assert g["edges"][0]["sla"]["owner"] == "external" and g["edges"][0]["sla"]["satisfy_moment"] == "arrival"
    assert g["end_to_end_sla"]["deadline_seconds"] == 86400 and g["end_to_end_sla"]["owner"] == "shared"


async def test_xor_and_fanout_graphs_are_valid(client):
    assert (await client.post("/cohort/definitions", json=_def(_xor_graph(), "xor_cohort"))).status_code == 201
    assert (await client.post("/cohort/definitions", json=_def(_and_fanout_graph(), "and_cohort"))).status_code == 201


# --- PUT replace (forward-only full-representation) --------------------------------------------------

async def test_put_replaces_then_clears_graph(client):
    await client.post("/cohort/definitions", json=_def())            # created without a graph
    before = (await client.get("/cohort/definitions/ach_exposure_cohort")).json()

    r = await client.put("/cohort/definitions/ach_exposure_cohort", json=_update_body(_linear_graph()))
    assert r.status_code == 200 and r.json()["expectation_graph"]["end_to_end_sla"]["deadline_seconds"] == 86400
    assert r.json()["created_at"] == before["created_at"] and r.json()["updated_at"] > before["created_at"]

    # omitting the graph on a subsequent PUT clears it (full-representation semantics)
    r2 = await client.put("/cohort/definitions/ach_exposure_cohort", json=_update_body())  # omit → None
    assert r2.status_code == 200 and r2.json()["expectation_graph"] is None


# --- rejections (422) with clear messages -----------------------------------------------------------

REJECTIONS = {
    "cycle": {
        "nodes": [{"node_id": "a"}, {"node_id": "b"}],
        "edges": [{"from_node": "__start__", "to_node": "a", "split": "and"},
                  {"from_node": "a", "to_node": "b", "split": "and"},
                  {"from_node": "b", "to_node": "a", "split": "and"},
                  {"from_node": "a", "to_node": "__close__", "split": "and"}]},
    "orphan": {
        "nodes": [{"node_id": "a"}, {"node_id": "b"}],
        "edges": [{"from_node": "__start__", "to_node": "a", "split": "and"},
                  {"from_node": "a", "to_node": "__close__", "split": "and"},
                  {"from_node": "b", "to_node": "__close__", "split": "and"}]},
    "dead-end": {
        "nodes": [{"node_id": "a"}, {"node_id": "b"}],
        "edges": [{"from_node": "__start__", "to_node": "a", "split": "and"},
                  {"from_node": "a", "to_node": "b", "split": "and"},
                  {"from_node": "a", "to_node": "__close__", "split": "and"}]},
    "__start__ cannot be an edge target": {
        "nodes": [{"node_id": "a"}],
        "edges": [{"from_node": "__start__", "to_node": "a", "split": "and"},
                  {"from_node": "a", "to_node": "__start__", "split": "and"},
                  {"from_node": "a", "to_node": "__close__", "split": "and"}]},
    "__close__ cannot be an edge source": {
        "nodes": [{"node_id": "a"}],
        "edges": [{"from_node": "__start__", "to_node": "a", "split": "and"},
                  {"from_node": "__close__", "to_node": "a", "split": "and"},
                  {"from_node": "a", "to_node": "__close__", "split": "and"}]},
    "must be 'conditional'": {  # XOR branch marked expected
        "nodes": [{"node_id": "a"}, {"node_id": "b", "node_type": "expected"}, {"node_id": "c", "node_type": "conditional"}],
        "edges": [{"from_node": "__start__", "to_node": "a", "split": "and"},
                  {"from_node": "a", "to_node": "b", "split": "xor"},
                  {"from_node": "a", "to_node": "c", "split": "xor"},
                  {"from_node": "b", "to_node": "__close__", "split": "and"},
                  {"from_node": "c", "to_node": "__close__", "split": "and"}]},
    "must be 'expected'": {  # AND branch marked conditional
        "nodes": [{"node_id": "a"}, {"node_id": "b", "node_type": "conditional"}],
        "edges": [{"from_node": "__start__", "to_node": "a", "split": "and"},
                  {"from_node": "a", "to_node": "b", "split": "and"},
                  {"from_node": "b", "to_node": "__close__", "split": "and"}]},
    "inconsistent split": {
        "nodes": [{"node_id": "a"}, {"node_id": "b"}, {"node_id": "c", "node_type": "conditional"}],
        "edges": [{"from_node": "__start__", "to_node": "a", "split": "and"},
                  {"from_node": "a", "to_node": "b", "split": "and"},
                  {"from_node": "a", "to_node": "c", "split": "xor"},
                  {"from_node": "b", "to_node": "__close__", "split": "and"},
                  {"from_node": "c", "to_node": "__close__", "split": "and"}]},
    "edge to unknown node 'ghost'": {
        "nodes": [{"node_id": "a"}],
        "edges": [{"from_node": "__start__", "to_node": "a", "split": "and"},
                  {"from_node": "a", "to_node": "ghost", "split": "and"},
                  {"from_node": "a", "to_node": "__close__", "split": "and"}]},
    "collides with a reserved id": {
        "nodes": [{"node_id": "__start__"}],
        "edges": [{"from_node": "__start__", "to_node": "__close__", "split": "and"}]},
    "at_risk_seconds must satisfy": {  # at_risk >= deadline
        "nodes": [{"node_id": "a"}],
        "edges": [{"from_node": "__start__", "to_node": "a", "split": "and",
                   "sla": {"deadline_seconds": 100, "at_risk_seconds": 100, "owner": "external"}},
                  {"from_node": "a", "to_node": "__close__", "split": "and"}]},
    "deadline_seconds must be > 0": {
        "nodes": [{"node_id": "a"}],
        "edges": [{"from_node": "__start__", "to_node": "a", "split": "and",
                   "sla": {"deadline_seconds": 0, "at_risk_seconds": 0, "owner": "external"}},
                  {"from_node": "a", "to_node": "__close__", "split": "and"}]},
}


@pytest.mark.parametrize("needle,graph", list(REJECTIONS.items()))
async def test_graph_rejections_422(client, needle, graph):
    r = await client.post("/cohort/definitions", json=_def(graph, "rej_cohort"))
    assert r.status_code == 422, f"expected 422 for '{needle}', got {r.status_code}: {r.text}"
    assert needle in r.json()["detail"], f"message '{r.json()['detail']}' missing '{needle}'"


# --- owner gate still holds with a graph body -------------------------------------------------------

async def test_graph_write_non_owner_403(cohort_def_repo):
    from amendia_auth import AuthContext, AuthenticatedUser, Principal, current_user
    from amendia_auth.resolver import INTERNAL_HEADER
    from amendia_auth.settings import AuthSettings
    from httpx import ASGITransport, AsyncClient
    from app.deps import get_cohort_def_repo
    from app.main import create_app

    app = create_app()
    app.state.auth = AuthContext(AuthSettings(issuer="t", internal_token="test-internal"))
    app.dependency_overrides[get_cohort_def_repo] = lambda: cohort_def_repo
    app.dependency_overrides[current_user] = lambda: AuthenticatedUser(
        amendia_user_id="usr-riya", roles={"role.payments.ops_analyst"}, principal=Principal(iss="t", sub="riya"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        post = await ac.post("/cohort/definitions", json=_def(_linear_graph()), headers={INTERNAL_HEADER: "test-internal"})
        put = await ac.put("/cohort/definitions/ach_exposure_cohort", json=_update_body(_linear_graph()),
                           headers={INTERNAL_HEADER: "test-internal"})
    assert post.status_code == 403 and put.status_code == 403
