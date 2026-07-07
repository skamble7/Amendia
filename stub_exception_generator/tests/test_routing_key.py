# tests/test_routing_key.py
from amendia_common.events import EXCEPTION_RAISED, Service, rk


def test_routing_key_delegates_to_rk():
    key = rk("bank-alpha", Service.STUBEXCEPTION, EXCEPTION_RAISED)
    assert key == "bank-alpha.stub_exception.exception_raised.v1"


def test_routing_key_uses_tenant_as_org():
    assert rk("acme", Service.STUBEXCEPTION, EXCEPTION_RAISED).startswith("acme.stub_exception.")
