# app/routers/resolve.py
"""Triage resolution endpoint (the lookup the ingestor will call)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.deps import get_resolver
from app.models.registry import NoMatchResponse, ResolveRequest, ResolveResponse
from app.services.resolver import ResolveService

router = APIRouter(tags=["resolve"])


@router.post("/resolve", response_model=ResolveResponse)
async def resolve(req: ResolveRequest, resolver: ResolveService = Depends(get_resolver)):
    result, considered = await resolver.resolve(req.tenant, req.envelope)
    if result is None:
        body = NoMatchResponse(tenant=req.tenant, considered_packs=considered)
        return JSONResponse(status_code=404, content=body.model_dump(mode="json"))
    return result
