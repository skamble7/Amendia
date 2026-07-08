# app/routers/health.py
"""Liveness + readiness (mongo ping + rabbit connection state)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.db.mongo import MongoClient
from app.deps import get_mongo, get_rabbit
from app.events.rabbit import RabbitConnection

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    mongo: MongoClient = Depends(get_mongo),
    rabbit: RabbitConnection = Depends(get_rabbit),
):
    mongo_ok = await mongo.ping()
    rabbit_ok = rabbit.is_ready
    return {
        "status": "ok",
        "ready": mongo_ok and rabbit_ok,
        "mongo": mongo_ok,
        "rabbit": rabbit_ok,
    }
