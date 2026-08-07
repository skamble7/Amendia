# tests/test_routing_key.py
from amendia_common.events import TRIGGER_RAISED, Service, rk


def test_routing_key_delegates_to_rk():
    key = rk(Service.TRIGGER_SOURCE, TRIGGER_RAISED)
    assert key == "trigger_source.trigger_raised.v1"
