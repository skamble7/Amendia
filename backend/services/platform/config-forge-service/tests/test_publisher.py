# tests/test_publisher.py
"""ADR-058 fast-follow — the ConfigRefResolvedEvent emit is correct + fail-soft (no Mongo / no broker)."""
from __future__ import annotations

from app.events.publisher import emit_config_ref_resolved


class FakePublisher:
    def __init__(self, ready: bool = True):
        self.is_ready = ready
        self.published: list = []

    async def publish(self, event: dict, routing_key: str, message_id: str) -> None:
        self.published.append((routing_key, event))


async def test_emit_noop_when_publisher_absent():
    await emit_config_ref_resolved(None, ref="dev.llm.nim", resolved=True)  # must not raise


async def test_emit_noop_when_not_ready():
    p = FakePublisher(ready=False)
    await emit_config_ref_resolved(p, ref="dev.llm.nim", resolved=True)
    assert p.published == []


async def test_emit_publishes_a_valid_governance_event():
    p = FakePublisher(ready=True)
    await emit_config_ref_resolved(p, ref="dev.llm.nim", resolved=False, actor="polyllm")
    assert len(p.published) == 1
    routing_key, ev = p.published[0]
    assert routing_key == "config_forge.config_ref_resolved.v1"
    assert ev["ref"] == "dev.llm.nim"
    assert ev["resolved"] is False
    assert ev["actor"] == "polyllm"
    # keyed by the ref (no instance context); the resolved VALUE never enters the event.
    assert ev["trace"]["correlation_id"] == "dev.llm.nim"


async def test_emit_is_fail_soft_on_publish_error():
    class Boom(FakePublisher):
        async def publish(self, *a, **k):
            raise RuntimeError("broker down")

    await emit_config_ref_resolved(Boom(), ref="x", resolved=True)  # a broker hiccup never breaks resolution
