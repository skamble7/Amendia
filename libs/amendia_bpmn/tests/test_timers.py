"""ADR-027 Phase 2.2 — timer parsing, the ``timers`` profile hierarchy, capture + coverage."""
from datetime import datetime, timezone

import pytest

from amendia_bpmn import (
    EXECUTION_PROFILES,
    TimerDef,
    UnsupportedTimer,
    compilability_findings,
    parse,
    parse_iso_duration,
    parse_timer,
    profile_rank,
    required_profile,
)

_HDR = ('<?xml version="1.0"?><bpmn:definitions '
        'xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">')
_FTR = "</bpmn:definitions>"


def _proc(inner: str) -> str:
    return f'{_HDR}<bpmn:process id="P" isExecutable="true">{inner}</bpmn:process>{_FTR}'


# --- linear core: start -> service -> (timer catch) -> end ------------------

def _catch_xml(duration="PT4H") -> str:
    dur = f"<bpmn:timeDuration>{duration}</bpmn:timeDuration>" if duration else ""
    return _proc(
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:serviceTask id="T"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:serviceTask>'
        f'<bpmn:intermediateCatchEvent id="Wait"><bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing>'
        f'<bpmn:timerEventDefinition>{dur}</bpmn:timerEventDefinition></bpmn:intermediateCatchEvent>'
        '<bpmn:endEvent id="E"><bpmn:incoming>f3</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="T"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="T" targetRef="Wait"/>'
        '<bpmn:sequenceFlow id="f3" sourceRef="Wait" targetRef="E"/>')


# --- HITL gate with an interrupting SLA boundary → escalation userTask -------

def _boundary_xml(duration="PT2H", host_kind="userTask") -> str:
    dur = f"<bpmn:timeDuration>{duration}</bpmn:timeDuration>" if duration else ""
    return _proc(
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        f'<bpmn:{host_kind} id="Approve"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:{host_kind}>'
        '<bpmn:endEvent id="EndOk"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:userTask id="Supervisor"><bpmn:incoming>fb</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing></bpmn:userTask>'
        '<bpmn:endEvent id="EndEsc"><bpmn:incoming>f3</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:boundaryEvent id="Sla" attachedToRef="Approve" cancelActivity="true">'
        f'<bpmn:timerEventDefinition>{dur}</bpmn:timerEventDefinition></bpmn:boundaryEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Approve"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="Approve" targetRef="EndOk"/>'
        '<bpmn:sequenceFlow id="fb" sourceRef="Sla" targetRef="Supervisor"/>'
        '<bpmn:sequenceFlow id="f3" sourceRef="Supervisor" targetRef="EndEsc"/>')


def _codes(model, profile):
    return {f.code for f in compilability_findings(model, profile=profile)}


# --------------------------------------------------------------------------- #
# Duration / timer parsing (2.2.b)
# --------------------------------------------------------------------------- #

def test_parse_iso_duration_forms():
    assert parse_iso_duration("PT4H").total_seconds() == 4 * 3600
    assert parse_iso_duration("PT30M").total_seconds() == 30 * 60
    assert parse_iso_duration("P1D").total_seconds() == 86400
    assert parse_iso_duration("P1DT2H30M").total_seconds() == 86400 + 2 * 3600 + 30 * 60


def test_parse_iso_duration_rejects_junk():
    for bad in ("", "4H", "P", "PT", "banana"):
        with pytest.raises(UnsupportedTimer):
            parse_iso_duration(bad)


def test_parse_timer_duration_and_date():
    base = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    assert parse_timer(TimerDef("duration", "PT4H"), base) == datetime(2026, 7, 17, 16, 0, tzinfo=timezone.utc)
    got = parse_timer(TimerDef("date", "2026-07-18T09:00:00Z"), base)
    assert got == datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc)


def test_parse_timer_cycle_and_empty_unsupported():
    base = datetime(2026, 7, 17, tzinfo=timezone.utc)
    with pytest.raises(UnsupportedTimer):
        parse_timer(TimerDef("cycle", "R3/PT10M"), base)
    with pytest.raises(UnsupportedTimer):
        parse_timer(TimerDef(None, None), base)


# --------------------------------------------------------------------------- #
# Profile hierarchy (2.2.e)
# --------------------------------------------------------------------------- #

def test_timers_profile_ranks_above_parallel():
    assert profile_rank("timers") == profile_rank("common_executable") == 1 > profile_rank("common_subset")


def test_required_profile_timers_for_catch_and_boundary():
    m, _ = parse(_catch_xml(), "P", profile="timers")
    assert required_profile(m) == "common_executable"
    m, _ = parse(_boundary_xml(), "P", profile="timers")
    assert required_profile(m) == "common_executable"


# --------------------------------------------------------------------------- #
# Capture + coverage tier (2.2.b / 2.2.e)
# --------------------------------------------------------------------------- #

def test_timer_catch_captured_and_executable_under_timers():
    m, _ = parse(_catch_xml(), "P", profile="timers")
    assert m.timer_catch_events["Wait"].value == "PT4H"
    assert next(e for e in m.elements if e.id == "Wait").tier == "executable"
    # under a lower profile it is captured but documented (coverage) + refused for execution
    m2, _ = parse(_catch_xml(), "P", profile="common_subset")
    assert "Wait" in m2.timer_catch_events
    assert next(e for e in m2.elements if e.id == "Wait").tier == "documented"


def test_boundary_timer_wired_and_removed_from_flows():
    m, _ = parse(_boundary_xml(), "P", profile="timers")
    bt = m.boundary_timers["Approve"]
    assert bt.id == "Sla" and bt.target == "Supervisor" and bt.cancel_activity is True
    assert bt.timer.value == "PT2H"
    # the boundary's outgoing flow is NOT a normal edge
    assert all(f.source != "Sla" for f in m.flows)
    # escalation target reached only via the boundary is NOT flagged unreachable
    codes = {f.code for f in _codes_all(m)}
    assert "bpmn_unreachable_node" not in codes


def _codes_all(model):
    _, fs = parse(_boundary_xml(), "P", profile="timers")
    return fs


def test_unwired_boundary_stays_documented():
    # a boundary with a timer but NO outgoing flow (off the live path) is documentation-only.
    xml = _proc(
        '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
        '<bpmn:userTask id="Approve"><bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:userTask>'
        '<bpmn:endEvent id="E"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>'
        '<bpmn:boundaryEvent id="Sla" attachedToRef="Approve"><bpmn:timerEventDefinition/></bpmn:boundaryEvent>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Approve"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="Approve" targetRef="E"/>')
    m, _ = parse(xml, "P", profile="timers")
    assert m.boundary_timers == {}
    assert next(e for e in m.elements if e.id == "Sla").tier == "documented"
    assert compilability_findings(m, profile="timers") == []


# --------------------------------------------------------------------------- #
# Compilability gate (2.2.e)
# --------------------------------------------------------------------------- #

def test_timers_refused_under_lower_profiles():
    m, _ = parse(_catch_xml(), "P", profile="common_subset")
    assert "bpmn_timer_unsupported" in _codes(m, "common_subset")
    assert "bpmn_timer_unsupported" in _codes(m, "common_subset")


def test_wellformed_timers_pass_under_timers_profile():
    assert compilability_findings(parse(_catch_xml(), "P", profile="timers")[0], profile="timers") == []
    assert compilability_findings(parse(_boundary_xml(), "P", profile="timers")[0], profile="timers") == []


def test_boundary_on_service_task_now_allowed():
    # ADR-040: a timer boundary on a capability serviceTask self-enforces an in-process running
    # deadline (was refused with bpmn_timer_boundary_host_unsupported; that host refusal is retired
    # for capability hosts — the read_only safety check lives in the registry validator).
    m, _ = parse(_boundary_xml(host_kind="serviceTask"), "P", profile="timers")
    assert "bpmn_timer_boundary_host_unsupported" not in _codes(m, "timers")
    assert "Approve" in m.boundary_timers  # captured as a running-deadline host


def test_empty_catch_schedule_is_rejected_under_timers():
    m, _ = parse(_catch_xml(duration=""), "P", profile="timers")
    assert "bpmn_timer_unsupported" in _codes(m, "timers")
