# tests/test_pack_edit.py
"""ADR-056: edit an activated pack's CONFIG by cloning it into a new version — reverse-hydrate a session from the
stored pack, edit through the stepped-review endpoints, publish (activate + auto-deprecate the prior), plus rollback
and version history. Domain-neutral (the mcp-screen payment fixture — not restaurant/wire)."""
import pytest

from app.models.onboarding import SetPoliciesRequest, SetTriageRequest, StagedTriageRule
from app.services.onboarding import TransitionError
from tests.test_roles import _walk_and_commit_with_meta

OWNER = "usr-owner"
_WHEN = {"field": "reason_codes", "op": "intersects", "value": ["AC01"]}


async def _base(svc):
    """Onboard + commit mcp-screen@1.0.0 to ACTIVE via the real pipeline."""
    return await _walk_and_commit_with_meta(svc, {})


async def _edit_and_publish(svc, s, *, priority):
    """A real config edit on the new version (change the triage priority), re-driven to ASSEMBLED, then published."""
    s = await svc.set_triage(s.session_id, SetTriageRequest(triage_rules=[
        StagedTriageRule(rule_id="r1", priority=priority, when=_WHEN)]), owner=OWNER)
    s = await svc.set_policies(s.session_id, SetPoliciesRequest(roles=["role.payments.ops_analyst"]), owner=OWNER)
    s = await svc.assemble(s.session_id, owner=OWNER)
    return await svc.commit(s.session_id, owner=OWNER)


async def test_hydrate_round_trips_the_pack_config(onboarding_service):
    svc = onboarding_service
    await _base(svc)
    s = await svc.create_edit_session("mcp-screen", bump="minor", owner=OWNER)

    assert s.basics.pack_key == "mcp-screen" and s.basics.version == "1.1.0"   # bumped from the active 1.0.0
    assert s.state.value == "assembled"                                         # fully editable, publish reachable
    b = next(x for x in s.bindings if x.element_id == "Task_Screen")
    assert b.executor_type == "capability" and b.capability_ref == "cap.payment.screen_party@^1.0.0"
    assert b.hitl_mode == "review_after" and b.hitl_role == "role.payments.ops_analyst"   # bindings round-trip
    assert [r.rule_id for r in s.triage_rules] == ["r1"]                        # triage round-trips
    assert "role.payments.ops_analyst" in s.roles                              # policies/roles round-trip
    assert any(sc.capability_id == "cap.payment.screen_party" for sc in s.staged_capabilities)  # caps rebuilt
    assert s.bpmn is not None and s.inferred is not None                       # BPMN + inference re-derived
    errs = [f for f in (s.dry_run_report or {}).get("findings", []) if f["severity"] == "error"]
    assert errs == []                                                          # re-validated clean


async def test_publish_activates_new_deprecates_prior_and_resolver_routes(onboarding_service, pack_repo, resolver):
    svc = onboarding_service
    await _base(svc)
    s = await svc.create_edit_session("mcp-screen", bump="minor", owner=OWNER)
    published = await _edit_and_publish(svc, s, priority=50)

    assert published.result_pack == "mcp-screen@1.1.0"
    assert (await pack_repo.get("mcp-screen", "1.1.0")).status.value == "active"
    assert (await pack_repo.get("mcp-screen", "1.0.0")).status.value == "deprecated"   # auto-deprecated on publish

    resolver.invalidate()
    result, _ = await resolver.resolve({"reason_codes": ["AC01"]})
    assert result is not None and result.pack_version == "1.1.0"               # NEW events route to the new version
    # a running instance pinned to 1.0.0 still loads its (deprecated) immutable stored bundle
    assert (await pack_repo.get_raw("mcp-screen", "1.0.0")) is not None


async def test_rollback_reactivates_prior_and_routes_back(client, onboarding_service, pack_repo, resolver):
    svc = onboarding_service
    await _base(svc)
    s = await svc.create_edit_session("mcp-screen", bump="minor", owner=OWNER)
    await _edit_and_publish(svc, s, priority=50)                               # 1.1.0 active, 1.0.0 deprecated

    r = await client.post("/packs/mcp-screen/rollback", json={"to_version": "1.0.0"})
    assert r.status_code == 200, r.text
    assert r.json()["version"] == "1.0.0" and r.json()["status"] == "active"
    assert (await pack_repo.get("mcp-screen", "1.0.0")).status.value == "active"
    assert (await pack_repo.get("mcp-screen", "1.1.0")).status.value == "deprecated"   # the newer one must be deprecated
    resolver.invalidate()
    result, _ = await resolver.resolve({"reason_codes": ["AC01"]})
    assert result.pack_version == "1.0.0"                                      # resolver routes to the rolled-back version

    # guards: unknown target → 404
    assert (await client.post("/packs/mcp-screen/rollback", json={"to_version": "9.9.9"})).status_code == 404


async def test_version_history_lists_all_versions_with_status(client, onboarding_service):
    svc = onboarding_service
    await _base(svc)
    s = await svc.create_edit_session("mcp-screen", bump="minor", owner=OWNER)
    await _edit_and_publish(svc, s, priority=50)

    r = await client.get("/packs/mcp-screen")
    assert r.status_code == 200
    assert {m["version"]: m["status"] for m in r.json()} == {"1.0.0": "deprecated", "1.1.0": "active"}


async def test_version_collision_guard(onboarding_service):
    svc = onboarding_service
    await _base(svc)
    # hydrating over an already-existing (pack_key, version) is refused
    with pytest.raises(TransitionError) as ei:
        await svc.hydrate_from_pack("mcp-screen", "1.0.0", "1.0.0", owner=OWNER)
    assert ei.value.status_code == 409


async def test_edit_missing_pack_is_404(onboarding_service):
    with pytest.raises(TransitionError) as ei:
        await onboarding_service.create_edit_session("no-such-pack", owner=OWNER)
    assert ei.value.status_code == 404
