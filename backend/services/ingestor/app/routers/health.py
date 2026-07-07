# app/routers/health.py
"""Liveness + readiness."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.db.mongo import MongoClient
from app.deps import get_consumer, get_mongo
from app.events.rabbit import RabbitConsumer

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    mongo: MongoClient = Depends(get_mongo),
    consumer: RabbitConsumer = Depends(get_consumer),
):
    mongo_ok = await mongo.ping()
    rabbit_ok = consumer.is_ready
    return {
        "status": "ok",
        "ready": mongo_ok and rabbit_ok,
        "mongo": mongo_ok,
        "rabbit": rabbit_ok,
    }
