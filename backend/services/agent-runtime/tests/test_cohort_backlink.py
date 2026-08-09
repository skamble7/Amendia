# tests/test_cohort_backlink.py
"""ADR-063 Phase 3A adjunct: GET /instances/{id} carries the cohort backlink fields (null for standalone)."""
from __future__ import annotations

from app.models.process_instance import ProcessInstance


async def _insert(instance_repo, pid, **cohort):
    inst = ProcessInstance.new(process_instance_id=pid, trigger_id=f"t-{pid}",
                               pack_key="wire-repair-standard", pack_version="1.0.0")
    for k, v in cohort.items():
        setattr(inst, k, v)
    await instance_repo.insert(inst)


async def test_instance_carries_cohort_backlink_when_joined(client, instance_repo):
    await _insert(instance_repo, "pi-joined", cohort_instance_id="coh-1",
                  cohort_def_id="wire_transfer_cohort", cohort_correlation_value="1v23p")
    body = (await client.get("/instances/pi-joined")).json()
    assert body["cohort_instance_id"] == "coh-1"
    assert body["cohort_def_id"] == "wire_transfer_cohort"
    assert body["cohort_correlation_value"] == "1v23p"


async def test_standalone_instance_has_null_cohort_fields(client, instance_repo):
    await _insert(instance_repo, "pi-standalone")
    body = (await client.get("/instances/pi-standalone")).json()
    assert body["cohort_instance_id"] is None
    assert body["cohort_def_id"] is None
    assert body["cohort_correlation_value"] is None
