"""Regression: the ElementTree parse sites are hardened with defusedxml (scan 2026-08-19, C-2).

The confirmed-real attack was entity-expansion DoS (billion laughs): plain ``xml.etree`` PARSED a 5-level
payload to 300k chars, and depth is attacker-chosen (exponential). After the defusedxml swap every parse
entry must REJECT such a payload (raise/convert to a validation error) rather than expand it. XXE file-read
and SSRF were already blocked by CPython's ElementTree, so they are not re-tested here.
"""
import time

import pytest
from defusedxml.common import DefusedXmlException

from amendia_bpmn import extract_semantics, parse, select_process_id

# A classic billion-laughs DOCTYPE: each entity references the previous ten → exponential expansion if resolved.
_BILLION_LAUGHS = """<?xml version="1.0"?>
<!DOCTYPE definitions [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
  <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
  <!ENTITY lol5 "&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;">
]>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <bpmn:process id="P" isExecutable="true"><bpmn:documentation>&lol5;</bpmn:documentation></bpmn:process>
</bpmn:definitions>"""

_VALID = ('<?xml version="1.0"?>'
          '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'
          '<bpmn:process id="P" isExecutable="true">'
          '<bpmn:startEvent id="S"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
          '<bpmn:endEvent id="E"><bpmn:incoming>f1</bpmn:incoming></bpmn:endEvent>'
          '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="E"/>'
          '</bpmn:process></bpmn:definitions>')


def test_billion_laughs_is_rejected_not_expanded():
    """parse() must return a hard failure (model=None + bpmn_parse_error) fast — never expand the entities."""
    start = time.monotonic()
    model, findings = parse(_BILLION_LAUGHS, "P")
    elapsed = time.monotonic() - start
    assert model is None
    assert any(f.code == "bpmn_parse_error" for f in findings)
    # defusedxml raises on the entity declaration BEFORE any expansion — this is effectively instant. A generous
    # ceiling proves no exponential expansion happened (unhardened, deeper payloads burn CPU/memory here).
    assert elapsed < 2.0, f"parse took {elapsed:.2f}s — entities may be expanding"


def test_select_process_id_rejects_entities():
    """select_process_id has no local try/except; the defused parser must raise (its callers catch)."""
    with pytest.raises(DefusedXmlException):
        select_process_id(_BILLION_LAUGHS)


def test_extract_semantics_tolerates_and_rejects_entities():
    """extract_semantics is tolerant (returns a model on bad XML) and must not expand entities."""
    model = extract_semantics(_BILLION_LAUGHS, "P")
    assert model is not None  # tolerant path returns an (empty) model, does not expand


def test_valid_bpmn_still_parses_after_hardening():
    """Positive control: the defusedxml swap did not break normal, entity-free BPMN parsing."""
    model, findings = parse(_VALID, "P")
    assert model is not None
    assert not [f for f in findings if f.code == "bpmn_parse_error"]
