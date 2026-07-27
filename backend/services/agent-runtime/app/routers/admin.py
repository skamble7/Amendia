# app/routers/admin.py
"""Admin surface: the seed trigger (guarded by AGENTRT_ENABLE_SEED_API)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.db.mongo import MongoClient
from app.deps import get_mongo
from app.seeding.load import SeedConflictError, SeedLoader

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/seed")
async def seed(mongo: MongoClient = Depends(get_mongo)):
    if not settings.ENABLE_SEED_API:
        # Flag off → the endpoint does not exist.
        raise HTTPException(status_code=404, detail="Not Found")
    if not settings.SEED_DIR:            # L2: nothing to seed unless a SEED_DIR is configured
        raise HTTPException(status_code=400, detail="no SEED_DIR configured")
    try:
        report = await SeedLoader(settings.SEED_DIR).load(mongo)
    except SeedConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return report.as_dict()
