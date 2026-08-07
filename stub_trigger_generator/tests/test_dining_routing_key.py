# tests/test_dining_routing_key.py — dine-in rides the SAME neutral raised-event routing key.
from amendia_common.events import TRIGGER_RAISED, Service, rk

from app.routers.generators import RAISED_ROUTING_KEY


def test_generators_publish_under_the_shared_raised_key():
    # Every generator (wire + dine-in) publishes the SAME raised-event key the triage chain consumes —
    # triage discriminates on the fetched payload's trigger_type, not on the routing key.
    assert RAISED_ROUTING_KEY == rk(Service.TRIGGER_SOURCE, TRIGGER_RAISED)
    assert RAISED_ROUTING_KEY == "trigger_source.trigger_raised.v1"
