# tests/test_dining_routing_key.py — mirrors test_routing_key.py for the dine-in path.
from amendia_common.events import EXCEPTION_RAISED, Service, rk

from app.routers.tickets import RAISED_ROUTING_KEY


def test_tickets_publish_under_the_shared_raised_key():
    # Dine-in tickets ride the SAME raised-event routing key the triage chain consumes — no wire collision,
    # because triage discriminates on the fetched payload's order_type, not on the routing key.
    assert RAISED_ROUTING_KEY == rk(Service.STUBEXCEPTION, EXCEPTION_RAISED)
    assert RAISED_ROUTING_KEY == "stub_exception.exception_raised.v1"
