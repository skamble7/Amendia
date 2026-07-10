# tests/test_routing_key.py
from amendia_common.events import EXCEPTION_RAISED, Service, rk


def test_routing_key_delegates_to_rk():
    key = rk(Service.STUBEXCEPTION, EXCEPTION_RAISED)
    assert key == "stub_exception.exception_raised.v1"
