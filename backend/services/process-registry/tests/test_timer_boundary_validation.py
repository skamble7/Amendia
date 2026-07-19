# tests/test_timer_boundary_validation.py
"""ADR-040 — a timer boundary on a side-effectful serviceTask host is refused at pack validation.

Interrupting a running side-effectful capability can leave a half-applied side effect (compensation,
deferred to Item G), so only a read_only host is allowed to self-enforce a running SLA deadline.
"""
from tests.conftest import load_bpmn, load_manifest, load_sample

_SLA = ('<bpmn:boundaryEvent id="Sla" attachedToRef="{host}"><bpmn:timerEventDefinition>'
        '<bpmn:timeDuration>PT2H</bpmn:timeDuration></bpmn:timerEventDefinition></bpmn:boundaryEvent>'
        '<bpmn:sequenceFlow id="Flow_Sla" sourceRef="Sla" targetRef="End_Returned"/>')


def _with_boundary(host: str) -> str:
    return load_bpmn().replace("</bpmn:process>", _SLA.format(host=host) + "</bpmn:process>")


async def _validate(cap_repo, schema_repo, bpmn):
    from app.validation.pack_validator import PackValidator
    v = PackValidator(cap_repo, schema_repo, profile="common_executable")
    return await v.validate(load_manifest(), bpmn, sample_envelopes=[load_sample()])


async def test_side_effectful_serviceTask_timer_boundary_refused(registered, cap_repo, schema_repo):
    # Task_ApplyRepair is bound to a side-effectful capability (apply_repair).
    report = await _validate(cap_repo, schema_repo, _with_boundary("Task_ApplyRepair"))
    assert "bpmn_timer_boundary_side_effect_unsupported" in set(report.error_codes())


async def test_read_only_serviceTask_timer_boundary_allowed(registered, cap_repo, schema_repo):
    # Task_EnrichPayment is read_only + autonomous → the SLA-deadline host is allowed (no timer refusal).
    report = await _validate(cap_repo, schema_repo, _with_boundary("Task_EnrichPayment"))
    codes = set(report.error_codes())
    assert "bpmn_timer_boundary_side_effect_unsupported" not in codes
    assert "bpmn_timer_boundary_host_unsupported" not in codes
