# app/routers/tickets.py
"""Tickets API: generate dine-in order tickets + fetch-back (mirrors the exceptions router).

A dine-in ticket rides the SAME thin "something was raised — go fetch it" event and routing key as a wire
exception (``stub_exception.exception_raised.v1``). There is no wire collision: triage discriminates on the
FETCHED payload's ``order_type`` (``dine_in`` → ``restaurant-dinein``), not on the routing key. The runtime and
ingestor stay domain-neutral — the domain lives only in the fetched document and the pack's triage rule.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from amendia_common.events import EXCEPTION_RAISED, Service, rk
from app.config import settings
from app.dal.tickets_repo import DuplicateTicketError, TicketRepository
from app.deps import get_publisher, get_ticket_repo
from app.dining_generator import generate_ticket
from app.events.rabbit import RabbitPublisher
from app.models.dining_api import GeneratedTicket, GenerateTicketRequest, GenerateTicketResponse
from app.models.events import ExceptionRaisedEvent
from app.models.ticket import SCHEMA_VERSION, PartySeatedEnvelope, StoredTicket

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tickets", tags=["tickets"])

# The shared raised-event routing key the triage chain consumes — tickets publish under it too (no wire clash).
RAISED_ROUTING_KEY = rk(Service.STUBEXCEPTION, EXCEPTION_RAISED)


def _to_stored(t: PartySeatedEnvelope) -> StoredTicket:
    now = datetime.now(timezone.utc)
    return StoredTicket(created_at=now, updated_at=now, **t.model_dump())


def _raised_event(t: PartySeatedEnvelope, base_url: str) -> ExceptionRaisedEvent:
    """The generic thin raised-event for a ticket. ``exception_type`` carries the trigger discriminator
    (``order_type``); the full ticket is fetched from ``fetch_url`` and triaged there."""
    return ExceptionRaisedEvent(
        exception_id=t.ticket_id,
        exception_type=t.order_type,
        fetch_url=f"{base_url.rstrip('/')}/tickets/{t.ticket_id}",
        schema_version=SCHEMA_VERSION,
    )


async def _persist_and_publish(
    t: PartySeatedEnvelope,
    repo: TicketRepository,
    publisher: RabbitPublisher,
) -> GeneratedTicket:
    """Insert first, then publish. A publish failure is surfaced, not rolled back (mirrors the wire path)."""
    stored = await repo.insert(_to_stored(t))  # may raise DuplicateTicketError

    event = _raised_event(t, settings.SERVICE_BASE_URL)
    published = False
    warning: Optional[str] = None
    try:
        await publisher.publish(event.model_dump(mode="json"), RAISED_ROUTING_KEY, event.event_id)
        published = True
    except Exception as exc:  # noqa: BLE001 - stub: log loudly, keep the insert
        warning = f"ticket persisted but event publish failed: {exc}"
        logger.error("Publish failed for ticket_id=%s: %s", t.ticket_id, exc)

    return GeneratedTicket(ticket=stored, routing_key=RAISED_ROUTING_KEY, published=published, warning=warning)


@router.post("/generate", response_model=GenerateTicketResponse, status_code=201)
async def generate(
    body: GenerateTicketRequest | None = None,
    repo: TicketRepository = Depends(get_ticket_repo),
    publisher: RabbitPublisher = Depends(get_publisher),
):
    req = body or GenerateTicketRequest()
    created = []
    for _ in range(req.count):
        ticket = generate_ticket(req)
        try:
            item = await _persist_and_publish(ticket, repo, publisher)
        except DuplicateTicketError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        created.append(item)
    return GenerateTicketResponse(created=created)


@router.get("/{ticket_id}", response_model=PartySeatedEnvelope)
async def get_ticket(ticket_id: str, repo: TicketRepository = Depends(get_ticket_repo)):
    """Fetch-back: return the clean DOMAIN trigger artifact (``art.dining.party_seated``), NOT the persisted
    row. Per ADR-047 D1 the fetched trigger must be exactly the domain payload — the pack's declared trigger
    schema is ``additionalProperties: false``, so serializing via ``PartySeatedEnvelope`` drops the store
    metadata (``schema_version`` / ``created_at`` / ``updated_at``) that would otherwise fail validation at
    dispatch. Lookup + 404 behaviour are unchanged; only the response SHAPE differs."""
    stored = await repo.get(ticket_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"Unknown ticket_id: {ticket_id}")
    return stored
