# app/routers/health.py
"""Liveness + readiness."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.db.mongo import MongoClient
from app.deps import get_mongo, get_publisher
from app.events.rabbit import RabbitPublisher

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    mongo: MongoClient = Depends(get_mongo),
    publisher: RabbitPublisher = Depends(get_publisher),
):
    mongo_ok = await mongo.ping()
    rabbit_ok = publisher.is_ready
    return {
        "status": "ok",
        "ready": mongo_ok and rabbit_ok,
        "mongo": mongo_ok,
        "rabbit": rabbit_ok,
    }
