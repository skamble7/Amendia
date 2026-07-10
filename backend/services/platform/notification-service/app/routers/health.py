# app/routers/health.py
"""Liveness/readiness — ready reflects the RabbitMQ consumer connection."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import get_consumer, get_hub
from app.events.consumer import BroadcastConsumer
from app.hub import NotificationHub

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    hub: NotificationHub = Depends(get_hub),
    consumer: BroadcastConsumer = Depends(get_consumer),
):
    return {"status": "ok", "ready": consumer.is_ready, "subscribers": hub.subscriber_count}
