# app/routers/health.py
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.db.mongo import MongoClient
from app.deps import get_mongo

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(mongo: MongoClient = Depends(get_mongo)):
    mongo_ok = await mongo.ping()
    return {"status": "ok", "ready": mongo_ok, "mongo": mongo_ok}
