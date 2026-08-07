# app/routers/generators.py
"""Trigger *generators* (ADR-059): a domain-neutral catalog the UI drives without knowing any domain, plus
one neutral generate endpoint per generator (``POST /generators/{generator_id}/generate``). Each generator
still calls its own DOMAIN generator (``generate_envelope`` / ``generate_ticket``); the router wraps the
produced domain envelope into a domain-blind ``StoredTrigger`` and publishes one generic
``TriggerRaisedEvent`` on ``rk(Service.TRIGGER_SOURCE, TRIGGER_RAISED)``.

Scenarios are DERIVED from the canonical sources — the wire ``ReasonCode`` set and the dine-in
``GenerateTicketRequest`` demo flags — so the catalog can never drift from what those generators accept.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, get_args

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError

from amendia_common.events import TRIGGER_RAISED, Service, rk
from app.config import settings
from app.contracts.party_seated import SCHEMA_VERSION as DINE_SCHEMA_VERSION
from app.contracts.wire_exception import SCHEMA_VERSION as WIRE_SCHEMA_VERSION
from app.dal.trigger_repo import DuplicateTriggerError, TriggerRepository
from app.deps import get_publisher, get_repo
from app.dining_generator import generate_ticket
from app.events.rabbit import RabbitPublisher
from app.generator import NARRATIVES, generate_envelope
from app.logging_conf import trigger_id_ctx
from app.models.api import GenerateRequest, ReasonCode
from app.models.dining_api import GenerateTicketRequest
from app.models.events import TriggerRaisedEvent
from app.models.trigger import StoredTrigger

logger = logging.getLogger(__name__)

router = APIRouter(tags=["generators"])

RAISED_ROUTING_KEY = rk(Service.TRIGGER_SOURCE, TRIGGER_RAISED)


class GeneratedTrigger(BaseModel):
    trigger: StoredTrigger
    routing_key: str
    published: bool
    warning: Optional[str] = None


class GenerateResponse(BaseModel):
    created: List[GeneratedTrigger]


# --------------------------------------------------------------------------- #
# catalog
# --------------------------------------------------------------------------- #
def _wire_scenarios() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for code in get_args(ReasonCode):
        short = NARRATIVES.get(code, "").split(";")[0].split(".")[0].strip() or code
        out.append({"id": code, "label": f"{code} · {short}", "body": {"reason_code": code}})
    return out


_DINEIN_FLAG_LABELS = {
    "with_nut_allergy": "Nut allergy · allergen-screen conflict",
}


def _dinein_scenarios() -> List[Dict[str, Any]]:
    flags = [name for name, f in GenerateTicketRequest.model_fields.items()
             if f.annotation is bool and f.default is False]
    unknown = set(_DINEIN_FLAG_LABELS) - set(flags)
    if unknown:
        raise RuntimeError(f"generators catalog references unknown dine-in flags: {sorted(unknown)}")
    out: List[Dict[str, Any]] = [{"id": "happy", "label": "Happy path", "body": {}}]
    for flag in flags:
        label = _DINEIN_FLAG_LABELS.get(flag)
        if label is not None:
            out.append({"id": flag, "label": label, "body": {flag: True}})
    return out


def build_catalog() -> Dict[str, Any]:
    """The generator catalog (computed from the canonical model sources). Each generator's ``endpoint``
    points at the neutral ``/generators/{id}/generate`` path."""
    return {
        "generators": [
            {"id": "wire", "label": "Wire exception", "endpoint": "/generators/wire/generate",
             "scenarios": _wire_scenarios()},
            {"id": "dine_in", "label": "Restaurant dine-in", "endpoint": "/generators/dine_in/generate",
             "scenarios": _dinein_scenarios()},
        ]
    }


@router.get("/generators")
async def list_generators() -> Dict[str, Any]:
    """List the trigger generators the UI can offer — each with its neutral generate endpoint + scenarios."""
    return build_catalog()


# --------------------------------------------------------------------------- #
# generate
# --------------------------------------------------------------------------- #
def _wrap(trigger_id: str, trigger_type: str, schema_version: str, source: str, payload: dict) -> StoredTrigger:
    now = datetime.now(timezone.utc)
    return StoredTrigger(trigger_id=trigger_id, trigger_type=trigger_type, schema_version=schema_version,
                         source=source, payload=payload, created_at=now, updated_at=now)


async def _persist_and_publish(stored: StoredTrigger, repo: TriggerRepository,
                               publisher: RabbitPublisher) -> GeneratedTrigger:
    """Insert first, then publish. A publish failure is surfaced, not rolled back."""
    saved = await repo.insert(stored)  # may raise DuplicateTriggerError
    event = TriggerRaisedEvent(
        schema_version=stored.schema_version,
        trigger_id=stored.trigger_id,
        trigger_type=stored.trigger_type,
        fetch_url=f"{settings.SERVICE_BASE_URL.rstrip('/')}/triggers/{stored.trigger_id}",
    )
    published = False
    warning: Optional[str] = None
    try:
        await publisher.publish(event.model_dump(mode="json"), RAISED_ROUTING_KEY, event.event_id)
        published = True
    except Exception as exc:  # noqa: BLE001 - stub: log loudly, keep the insert
        warning = f"trigger persisted but event publish failed: {exc}"
        logger.error("Publish failed for trigger_id=%s: %s", stored.trigger_id, exc)
    return GeneratedTrigger(trigger=saved, routing_key=RAISED_ROUTING_KEY, published=published, warning=warning)


def _generate_stored(generator_id: str, body: Optional[dict]) -> List[StoredTrigger]:
    """Dispatch to the domain generator by generator id and wrap each produced envelope into a StoredTrigger.
    An invalid request body surfaces as HTTP 422 (parity with FastAPI body validation)."""
    try:
        if generator_id == "wire":
            req = GenerateRequest(**(body or {}))
            return [
                _wrap(env.exception_id, env.exception_type, WIRE_SCHEMA_VERSION, "wire",
                      env.model_dump(mode="json"))
                for env in (generate_envelope(req, settings.SERVICE_BASE_URL) for _ in range(req.count))
            ]
        if generator_id == "dine_in":
            req = GenerateTicketRequest(**(body or {}))
            return [
                _wrap(t.ticket_id, t.order_type, DINE_SCHEMA_VERSION, "dine_in", t.model_dump(mode="json"))
                for t in (generate_ticket(req) for _ in range(req.count))
            ]
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())
    raise HTTPException(status_code=404, detail=f"Unknown generator '{generator_id}'")


@router.post("/generators/{generator_id}/generate", response_model=GenerateResponse, status_code=201)
async def generate(
    generator_id: str,
    body: Optional[dict] = None,
    repo: TriggerRepository = Depends(get_repo),
    publisher: RabbitPublisher = Depends(get_publisher),
):
    """Generate one or more triggers for ``generator_id`` (``wire`` | ``dine_in``), persist each as a
    ``StoredTrigger``, and publish a ``TriggerRaisedEvent``. Replaces ``/exceptions/generate`` and
    ``/tickets/generate``."""
    created = []
    for stored in _generate_stored(generator_id, body):
        token = trigger_id_ctx.set(stored.trigger_id)
        try:
            item = await _persist_and_publish(stored, repo, publisher)
        except DuplicateTriggerError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        finally:
            trigger_id_ctx.reset(token)
        created.append(item)
    return GenerateResponse(created=created)
