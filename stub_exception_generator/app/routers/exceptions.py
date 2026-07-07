# app/routers/exceptions.py
"""Exceptions API: generate, fetch-back, list, and serve attachment bytes."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from amendia_common.events import EXCEPTION_RAISED, Service, rk
from app.config import settings
from app.dal.exceptions_repo import DuplicateExceptionError, ExceptionRepository
from app.deps import get_publisher, get_repo
from app.events.rabbit import RabbitPublisher
from app.generator import generate_envelope
from app.logging_conf import exception_id_ctx
from app.models.api import GenerateRequest, GeneratedItem, GenerateResponse
from app.models.envelope import StoredException, WireExceptionEnvelope
from app.models.events import ExceptionRaisedEvent
from app.sample_data import CATALOG, read_bytes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/exceptions", tags=["exceptions"])


def _to_stored(env: WireExceptionEnvelope) -> StoredException:
    now = datetime.now(timezone.utc)
    return StoredException(created_at=now, updated_at=now, **env.model_dump())


async def _persist_and_publish(
    env: WireExceptionEnvelope,
    repo: ExceptionRepository,
    publisher: RabbitPublisher,
) -> GeneratedItem:
    """Insert first, then publish. A publish failure is surfaced, not rolled back."""
    stored = await repo.insert(_to_stored(env))  # may raise DuplicateExceptionError

    event = ExceptionRaisedEvent.from_envelope(env, settings.SERVICE_BASE_URL)
    routing_key = rk(env.tenant, Service.STUBEXCEPTION, EXCEPTION_RAISED)

    published = False
    warning: Optional[str] = None
    try:
        await publisher.publish(event.model_dump(mode="json"), routing_key, event.event_id)
        published = True
    except Exception as exc:  # noqa: BLE001 - stub: log loudly, keep the insert
        warning = f"exception persisted but event publish failed: {exc}"
        logger.error("Publish failed for exception_id=%s: %s", env.exception_id, exc)

    return GeneratedItem(exception=stored, routing_key=routing_key, published=published, warning=warning)


@router.post("/generate", response_model=GenerateResponse, status_code=201)
async def generate(
    body: GenerateRequest | None = None,
    repo: ExceptionRepository = Depends(get_repo),
    publisher: RabbitPublisher = Depends(get_publisher),
):
    req = body or GenerateRequest()
    created = []
    for _ in range(req.count):
        env = generate_envelope(req, settings.SERVICE_BASE_URL, settings.DEFAULT_TENANT)
        token = exception_id_ctx.set(env.exception_id)
        try:
            item = await _persist_and_publish(env, repo, publisher)
        except DuplicateExceptionError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        finally:
            exception_id_ctx.reset(token)
        created.append(item)
    return GenerateResponse(created=created)


@router.get("", response_model=list[StoredException])
async def list_exceptions(
    tenant: Optional[str] = Query(None),
    exception_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    reason_code: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    repo: ExceptionRepository = Depends(get_repo),
):
    return await repo.list(
        tenant=tenant,
        exception_type=exception_type,
        status=status,
        reason_code=reason_code,
        limit=limit,
        offset=offset,
    )


@router.get("/{exception_id}", response_model=StoredException)
async def get_exception(exception_id: str, repo: ExceptionRepository = Depends(get_repo)):
    stored = await repo.get(exception_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"Unknown exception_id: {exception_id}")
    return stored


@router.get("/{exception_id}/attachments/{attachment_id}")
async def get_attachment(
    exception_id: str,
    attachment_id: str,
    repo: ExceptionRepository = Depends(get_repo),
):
    stored = await repo.get(exception_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"Unknown exception_id: {exception_id}")

    att = next((a for a in stored.attachments if a.attachment_id == attachment_id), None)
    if att is None or attachment_id not in CATALOG:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown attachment '{attachment_id}' on exception {exception_id}",
        )

    return Response(content=read_bytes(attachment_id), media_type=att.media_type)
