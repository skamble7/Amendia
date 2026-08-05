# app/routers/health.py
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import get_consumer
from app.events.consumer import AuditConsumer

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(consumer: AuditConsumer = Depends(get_consumer)):
    return {"status": "ok", "ready": consumer.is_ready}
